"""One-document application assembly; stop and preserve state at the first failure."""

import argparse
import json
import logging
from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from zipfile import ZipFile

from PIL import Image

from datasets.registry import DatasetManager

LOGGER = logging.getLogger("cdp.application")
STAGES = ("load", "classification", "template_selection", "registration", "geometry", "ocr", "ranking",
          "validators", "decision", "evidence")

# A disabled optional step is not the registration failure. Reporting it as the
# terminal reason hid LightGlue rejections behind the Azure DI cost gate.
_MASKED_REGISTRATION_REASONS = frozenset({
    "AZURE_DI_PAGE_CORNERS_DISABLED_LOW_COST",
})


def _terminal_failure_reason(attempts: list | None) -> str:
    for attempt in reversed(attempts or []):
        reason = str((attempt or {}).get("reason") or "")
        if reason and reason not in _MASKED_REGISTRATION_REASONS:
            return reason
    if attempts:
        return str((attempts[-1] or {}).get("reason") or "REGISTRATION_NOT_ACCEPTED")
    return "REGISTRATION_NOT_ACCEPTED"


def register_classified_document(images, routing, registry, selection=None):
    """Bind the selected page to existing image registration, without field geometry.

    Registration acceptance does not authorize extraction or establish form identity.
    No page-corner correspondences or substitute template are manufactured.

    CMS-1500 path: when geometric registration is accepted but patient-identity ROIs
    OCR insurance-type text (wrong-ROI / misalignment failure mode), reject and allow
    one bounded CLAHE/denoise enhancement retry against the same template.
    """
    from packages.domain.enums import ClaimFormType
    from packages.recovery.azure_di_page_corners import run_azure_di_page_corners
    from packages.recovery.document_quad import (
        compose_source_to_template,
        detect_document_quad,
    )
    from packages.recovery.orientation_hint import ordered_orientation_attempts
    from packages.recovery.planner import Strategy
    from packages.recovery.registration_content import validate_cms1500_registration_content
    from packages.recovery.registration_near_miss import (
        assess_evidence_near_miss,
        best_orientation_rotation_degrees,
        content_corroboration_eligible,
        should_attempt_azure_di_page_corners,
        should_attempt_document_quad_recovery,
        should_attempt_document_quad_recovery_any,
        should_attempt_learned_matcher,
        should_attempt_learned_matcher_any,
        should_attempt_near_miss_boost,
        should_attempt_near_miss_boost_any,
        should_attempt_orientation_recovery_any,
        should_attempt_perspective_recovery,
        should_attempt_perspective_recovery_any,
    )
    from packages.recovery.registration_recovery import (
        decide_registration_recovery,
        enhance_for_registration,
        enhance_for_registration_contrast_stretch,
        enhance_for_registration_edge_deskew,
        enhance_for_registration_strong,
        evidence_grade_alignment_confidence,
        rotate_page_for_orientation,
        should_attempt_second_preprocess,
    )
    from workers.page_detection.registration_telemetry import registration_context
    from workers.page_detection.template_alignment import (
        AlignmentResult,
        align_learned_matcher,
        align_near_miss_boosted,
        align_perspective_recovery,
        align_to_reference,
    )

    if selection is not None:
        if selection.template_id is None:
            return {"status": "UNAVAILABLE", "accepted": False, "reason": selection.reason,
                    "page_number": None, "evidence": None, "transform_matrix": None}
        from types import SimpleNamespace

        routing = SimpleNamespace(
            needs_review=False, selected_page_number=selection.page_number,
            template=registry.get(selection.template_id, selection.template_version),
        )
    result = {"status": "UNAVAILABLE", "accepted": False, "reason": None,
              "page_number": routing.selected_page_number, "evidence": None,
              "transform_matrix": None}
    if routing.needs_review or routing.template is None or routing.selected_page_number is None:
        result["reason"] = "CLASSIFICATION_HAS_NO_UNAMBIGUOUS_TEMPLATE_PAGE"
        return result
    page_number = routing.selected_page_number
    if not 1 <= page_number <= len(images):
        result.update(status="FAILED", reason="SELECTED_PAGE_OUT_OF_RANGE")
        return result
    template = routing.template
    result.update(template_id=template.template_id, template_version=template.version)
    reference = registry.load_reference_image(template)
    if reference is None:
        result["reason"] = "REFERENCE_TEMPLATE_IMAGE_UNAVAILABLE"
        return result

    def _identity_boxes():
        name = template.field_region("patient_name")
        dob = template.field_region("patient_dob")
        if name is None or dob is None:
            return None
        return (
            (name.x0, name.y0, name.x1, name.y1),
            (dob.x0, dob.y0, dob.x1, dob.y1),
        )

    def _attempt(image, attempt_name, *, enforce_compatibility_precheck=True):
        with registration_context(template_id=template.template_id, page_number=page_number):
            aligned = align_to_reference(
                image, reference, family=template.form_type.value,
                enforce_compatibility_precheck=enforce_compatibility_precheck,
            )
        evidence = aligned.evidence
        accepted = (aligned.success and aligned.accepted and aligned.warped is not None
                    and evidence is not None and evidence.accepted
                    and evidence.corner_validity is True)
        meta = {
            "attempt": attempt_name,
            "accepted": accepted,
            "alignment_confidence": (
                evidence.alignment_confidence if evidence is not None else aligned.alignment_score
            ),
            "reason": (
                "REGISTRATION_ACCEPTED" if accepted else (
                    evidence.rejection_reason if evidence and evidence.rejection_reason
                    else "REGISTRATION_NOT_ACCEPTED"
                )
            ),
        }
        content_ok = True
        content_reason = None
        if (
            accepted
            and template.form_type == ClaimFormType.CMS1500
            and aligned.warped is not None
        ):
            boxes = _identity_boxes()
            if boxes is not None:
                content = validate_cms1500_registration_content(
                    aligned.warped,
                    patient_name_box=boxes[0],
                    patient_dob_box=boxes[1],
                )
                content_ok = content.accepted
                content_reason = content.reason
                meta["content_ok"] = content.accepted
                meta["content_reason"] = content.reason
                if not content.accepted:
                    accepted = False
                    meta["accepted"] = False
                    meta["reason"] = "REGISTRATION_CONTENT_MISMATCH"
        return aligned, evidence, accepted, meta, content_ok, content_reason

    aligned = None
    attempts = []
    recovery_strategies = []
    orientation_evidence_trail: list = []
    try:
        size = (template.reference_dimensions.width_px, template.reference_dimensions.height_px)
        if reference.size != size:
            resized = reference.resize(size)
            reference.close()
            reference = resized

        source = images[page_number - 1]
        aligned, evidence, accepted, meta, content_ok, content_reason = _attempt(source, "primary")
        attempts.append(meta)
        if evidence is not None:
            orientation_evidence_trail.append(evidence)

        # Template already selected (ops / selector). Lineage precheck must not
        # hard-stop before SIFT — that left Track-A HITL with zero geometric tries.
        bypass_lineage_precheck = False
        if not accepted and str(meta.get("reason") or "") == "template_lineage_mismatch":
            if aligned is not None and aligned.warped is not None:
                aligned.warped.close()
                aligned = None
            recovery_strategies.append("LINEAGE_PRECHECK_BYPASS")
            bypass_lineage_precheck = True
            aligned, evidence, accepted, meta, content_ok, content_reason = _attempt(
                source,
                "lineage_bypass",
                enforce_compatibility_precheck=False,
            )
            attempts.append(meta)
            if evidence is not None:
                orientation_evidence_trail.append(evidence)

        recovery_decision = None
        if not accepted:
            failure_reasons = [
                value for value in (
                    meta.get("reason"),
                    evidence.rejection_reason if evidence else None,
                ) if value
            ]
            # Rejection reasons may be comma-joined gate tokens from alignment.
            expanded: list[str] = []
            for value in failure_reasons:
                expanded.extend(part.strip() for part in str(value).split(",") if part.strip())
            recovery_decision = decide_registration_recovery(
                failure_reasons=expanded or failure_reasons,
                content_invalid=not content_ok,
                strategy_available=True,
            )
            if recovery_decision.attempt:
                recovery_strategies.append(recovery_decision.strategy.value)

        # Early orientation: if primary/lineage already looks like a phone-rotated
        # capture, try cardinal rotates before burning enhance/near-miss budget.
        if (
            not accepted
            and should_attempt_orientation_recovery_any(orientation_evidence_trail)
            and "ORIENTATION_ROTATE_RETRY" not in recovery_strategies
        ):
            if aligned is not None and aligned.warped is not None:
                aligned.warped.close()
                aligned = None
            rot_hint = best_orientation_rotation_degrees(orientation_evidence_trail)
            degree_order = ordered_orientation_attempts(
                source, rotation_degrees=rot_hint
            )
            best_orient = None
            best_orient_key = (-1, -1.0)
            for degrees in degree_order:
                rotated = rotate_page_for_orientation(source, degrees)
                try:
                    with registration_context(
                        template_id=template.template_id, page_number=page_number
                    ):
                        oriented = align_to_reference(
                            rotated,
                            reference,
                            family=template.form_type.value,
                            enforce_compatibility_precheck=False,
                        )
                    ev = oriented.evidence
                    key = (
                        1 if oriented.accepted else 0,
                        float(ev.inlier_ratio) if ev is not None else 0.0,
                    )
                    if key > best_orient_key:
                        if best_orient is not None and best_orient.warped is not None:
                            best_orient.warped.close()
                        best_orient = oriented
                        best_orient_key = key
                    elif oriented.warped is not None:
                        oriented.warped.close()
                    if oriented.accepted:
                        break
                finally:
                    rotated.close()
            if best_orient is not None:
                evidence = best_orient.evidence
                accepted_geom = (
                    best_orient.success
                    and best_orient.accepted
                    and best_orient.warped is not None
                    and evidence is not None
                    and evidence.accepted
                    and evidence.corner_validity is True
                )
                meta = {
                    "attempt": "orientation_recovery_early",
                    "accepted": accepted_geom,
                    "alignment_confidence": (
                        evidence.alignment_confidence
                        if evidence is not None
                        else best_orient.alignment_score
                    ),
                    "reason": (
                        "REGISTRATION_ACCEPTED"
                        if accepted_geom
                        else (
                            evidence.rejection_reason
                            if evidence and evidence.rejection_reason
                            else "REGISTRATION_NOT_ACCEPTED"
                        )
                    ),
                }
                content_ok = True
                content_reason = None
                if (
                    accepted_geom
                    and template.form_type == ClaimFormType.CMS1500
                    and best_orient.warped is not None
                ):
                    boxes = _identity_boxes()
                    if boxes is not None:
                        content = validate_cms1500_registration_content(
                            best_orient.warped,
                            patient_name_box=boxes[0],
                            patient_dob_box=boxes[1],
                        )
                        content_ok = content.accepted
                        content_reason = content.reason
                        meta["content_ok"] = content.accepted
                        meta["content_reason"] = content.reason
                        if not content.accepted:
                            accepted_geom = False
                            meta["accepted"] = False
                            meta["reason"] = "REGISTRATION_CONTENT_MISMATCH"
                accepted = accepted_geom
                aligned = best_orient
                attempts.append(meta)
                recovery_strategies.append("ORIENTATION_ROTATE_RETRY")
                if evidence is not None:
                    orientation_evidence_trail.append(evidence)

        if (
            not accepted
            and recovery_decision is not None
            and recovery_decision.attempt
        ):
            if aligned is not None and aligned.warped is not None:
                aligned.warped.close()
                aligned = None
            if recovery_decision.strategy is Strategy.ALTERNATIVE_REGISTRATION:
                enhanced = enhance_for_registration_strong(source)
                attempt_name = "enhanced_strong"
            else:
                enhanced = enhance_for_registration(source)
                attempt_name = "enhanced"
            try:
                aligned, evidence, accepted, meta, content_ok, content_reason = _attempt(
                    enhanced,
                    attempt_name,
                    enforce_compatibility_precheck=not bypass_lineage_precheck,
                )
                attempts.append(meta)
                if evidence is not None:
                    orientation_evidence_trail.append(evidence)
            finally:
                enhanced.close()

        # Second distinct preprocess when cause-specific enhance still fails.
        if (
            not accepted
            and recovery_decision is not None
            and recovery_decision.attempt
        ):
            failure_reasons = [
                value for value in (
                    meta.get("reason"),
                    evidence.rejection_reason if evidence else None,
                ) if value
            ]
            expanded = []
            for value in failure_reasons:
                expanded.extend(part.strip() for part in str(value).split(",") if part.strip())
            if should_attempt_second_preprocess(
                failure_reasons=expanded or failure_reasons,
                first_recovery_attempted=True,
            ):
                if aligned is not None and aligned.warped is not None:
                    aligned.warped.close()
                    aligned = None
                recovery_strategies.append("CONTRAST_STRETCH_SECOND_PREPROCESS")
                enhanced = enhance_for_registration_contrast_stretch(source)
                try:
                    aligned, evidence, accepted, meta, content_ok, content_reason = _attempt(
                        enhanced,
                        "enhanced_contrast_stretch",
                        enforce_compatibility_precheck=not bypass_lineage_precheck,
                    )
                    attempts.append(meta)
                    if evidence is not None:
                        orientation_evidence_trail.append(evidence)
                finally:
                    enhanced.close()

        # Near-miss Step 1: boosted SIFT + multi-scale (same Acceptance gates).
        gap = assess_evidence_near_miss(evidence) if evidence is not None else None
        best_corroboration_aligned = None
        best_corroboration_evidence = None

        def _preserve_corroboration_candidate(current_aligned, current_evidence):
            nonlocal best_corroboration_aligned, best_corroboration_evidence
            if current_evidence is None or current_aligned is None:
                return
            if not content_corroboration_eligible(current_evidence):
                return
            if current_aligned.warped is None or current_aligned.homography is None:
                return
            prev = (
                best_corroboration_evidence.inlier_count
                if best_corroboration_evidence is not None
                else -1
            )
            if current_evidence.inlier_count >= prev:
                if (
                    best_corroboration_aligned is not None
                    and best_corroboration_aligned is not current_aligned
                    and best_corroboration_aligned.warped is not None
                ):
                    best_corroboration_aligned.warped.close()
                best_corroboration_aligned = current_aligned
                best_corroboration_evidence = current_evidence

        def _apply_alignment_result(aligned_result, attempt_name, strategy_name):
            nonlocal aligned, evidence, accepted, meta, content_ok, content_reason, gap
            evidence = aligned_result.evidence
            accepted_geom = (
                aligned_result.success
                and aligned_result.accepted
                and aligned_result.warped is not None
                and evidence is not None
                and evidence.accepted
                and evidence.corner_validity is True
            )
            meta = {
                "attempt": attempt_name,
                "accepted": accepted_geom,
                "alignment_confidence": (
                    evidence.alignment_confidence
                    if evidence is not None
                    else aligned_result.alignment_score
                ),
                "reason": (
                    "REGISTRATION_ACCEPTED"
                    if accepted_geom
                    else (
                        evidence.rejection_reason
                        if evidence and evidence.rejection_reason
                        else "REGISTRATION_NOT_ACCEPTED"
                    )
                ),
                "registration_gap_class": (
                    assess_evidence_near_miss(evidence).gap_class
                    if evidence is not None
                    else None
                ),
            }
            content_ok = True
            content_reason = None
            if (
                accepted_geom
                and template.form_type == ClaimFormType.CMS1500
                and aligned_result.warped is not None
            ):
                boxes = _identity_boxes()
                if boxes is not None:
                    content = validate_cms1500_registration_content(
                        aligned_result.warped,
                        patient_name_box=boxes[0],
                        patient_dob_box=boxes[1],
                    )
                    content_ok = content.accepted
                    content_reason = content.reason
                    meta["content_ok"] = content.accepted
                    meta["content_reason"] = content.reason
                    if not content.accepted:
                        accepted_geom = False
                        meta["accepted"] = False
                        meta["reason"] = "REGISTRATION_CONTENT_MISMATCH"
            accepted = accepted_geom
            aligned = aligned_result
            attempts.append(meta)
            recovery_strategies.append(strategy_name)
            gap = assess_evidence_near_miss(evidence) if evidence is not None else None
            if evidence is not None:
                orientation_evidence_trail.append(evidence)
            if not accepted:
                _preserve_corroboration_candidate(aligned, evidence)

        if (
            not accepted
            and (
                should_attempt_near_miss_boost_any(orientation_evidence_trail)
                or (
                    evidence is not None and should_attempt_near_miss_boost(evidence)
                )
            )
        ):
            # Boost re-runs SIFT on the source page — do not require the latest
            # failed attempt to still hold a warped buffer (trail-aware gate).
            if aligned is not None:
                _preserve_corroboration_candidate(aligned, evidence)
                if (
                    best_corroboration_aligned is not aligned
                    and aligned.warped is not None
                ):
                    aligned.warped.close()
                aligned = None
            boost_source = enhance_for_registration_strong(source)
            try:
                with registration_context(
                    template_id=template.template_id, page_number=page_number
                ):
                    boosted = align_near_miss_boosted(
                        boost_source,
                        reference,
                        family=template.form_type.value,
                    )
                _apply_alignment_result(
                    boosted, "near_miss_boost", "NEAR_MISS_SIFT_BOOST_MULTISCALE"
                )
            finally:
                boost_source.close()

        # Perspective Step 3: edge-deskew preprocess + affine-first / boosted SIFT.
        if (
            not accepted
            and (
                should_attempt_perspective_recovery_any(orientation_evidence_trail)
                or (
                    evidence is not None
                    and should_attempt_perspective_recovery(evidence)
                )
            )
        ):
            if aligned is not None:
                _preserve_corroboration_candidate(aligned, evidence)
                if (
                    best_corroboration_aligned is not aligned
                    and aligned.warped is not None
                ):
                    aligned.warped.close()
                aligned = None
            deskewed = enhance_for_registration_edge_deskew(source)
            try:
                with registration_context(
                    template_id=template.template_id, page_number=page_number
                ):
                    recovered = align_perspective_recovery(
                        deskewed,
                        reference,
                        family=template.form_type.value,
                    )
                _apply_alignment_result(
                    recovered,
                    "perspective_recovery",
                    "PERSPECTIVE_EDGE_DESKEW_AFFINE",
                )
            finally:
                deskewed.close()

        # Orientation Step 4: ranked 180/90/270 when ANY ladder attempt looked
        # orientation-recoverable (skip if early orientation already ran).
        if (
            not accepted
            and "ORIENTATION_ROTATE_RETRY" not in recovery_strategies
            and should_attempt_orientation_recovery_any(orientation_evidence_trail)
        ):
            if aligned is not None and aligned.warped is not None:
                if best_corroboration_aligned is not aligned:
                    aligned.warped.close()
                aligned = None
            rot_hint = best_orientation_rotation_degrees(orientation_evidence_trail)
            degree_order = ordered_orientation_attempts(
                source, rotation_degrees=rot_hint
            )
            best_orient = None
            best_orient_key = (-1, -1.0)
            for degrees in degree_order:
                rotated = rotate_page_for_orientation(source, degrees)
                try:
                    with registration_context(
                        template_id=template.template_id, page_number=page_number
                    ):
                        # Same already-selected template; rotation must not be
                        # blocked by lineage precheck (rotated pages often trip
                        # template_lineage_mismatch before SIFT can recover).
                        oriented = align_to_reference(
                            rotated,
                            reference,
                            family=template.form_type.value,
                            enforce_compatibility_precheck=False,
                        )
                    ev = oriented.evidence
                    key = (
                        1 if oriented.accepted else 0,
                        float(ev.inlier_ratio) if ev is not None else 0.0,
                    )
                    if key > best_orient_key:
                        if best_orient is not None and best_orient.warped is not None:
                            best_orient.warped.close()
                        best_orient = oriented
                        best_orient_key = key
                    elif oriented.warped is not None:
                        oriented.warped.close()
                    if oriented.accepted:
                        break
                finally:
                    rotated.close()
            if best_orient is not None:
                _apply_alignment_result(
                    best_orient,
                    "orientation_recovery",
                    "ORIENTATION_ROTATE_RETRY",
                )

        # Catastrophic Step 5: document-quad crop → re-SIFT; compose H so
        # geometry still warps the original page (not the rectified crop).
        if (
            not accepted
            and "DOCUMENT_QUAD_RECOVERY" not in recovery_strategies
            and (
                should_attempt_document_quad_recovery_any(orientation_evidence_trail)
                or (
                    evidence is not None
                    and should_attempt_document_quad_recovery(evidence)
                )
            )
        ):
            if aligned is not None:
                _preserve_corroboration_candidate(aligned, evidence)
                if (
                    best_corroboration_aligned is not aligned
                    and aligned.warped is not None
                ):
                    aligned.warped.close()
                aligned = None
            quad = detect_document_quad(source)
            if quad is not None:
                try:
                    with registration_context(
                        template_id=template.template_id, page_number=page_number
                    ):
                        cropped_aligned = align_to_reference(
                            quad.rectified,
                            reference,
                            family=template.form_type.value,
                            enforce_compatibility_precheck=False,
                        )
                    if (
                        cropped_aligned.homography is not None
                        and cropped_aligned.warped is not None
                    ):
                        import cv2
                        import numpy as np

                        composed = compose_source_to_template(
                            quad.source_to_rectified,
                            cropped_aligned.homography,
                        )
                        # Rebuild warp from the original page with composed H.
                        size = (
                            template.reference_dimensions.width_px,
                            template.reference_dimensions.height_px,
                        )
                        source_gray = np.asarray(source.convert("L"), dtype=np.uint8)
                        warped_arr = cv2.warpPerspective(
                            source_gray, composed, size, borderValue=255
                        )
                        if cropped_aligned.warped is not None:
                            cropped_aligned.warped.close()
                        evidence_out = cropped_aligned.evidence
                        if evidence_out is not None:
                            evidence_out = evidence_out.model_copy(
                                update={
                                    "algorithm": "document_quad_then_sift",
                                    "transform_matrix": composed.tolist(),
                                }
                            )
                        composed_aligned = AlignmentResult(
                            cropped_aligned.success,
                            cropped_aligned.alignment_score,
                            cropped_aligned.good_match_count,
                            composed,
                            Image.fromarray(warped_arr),
                            "document_quad_then_sift",
                            cropped_aligned.inlier_ratio,
                            cropped_aligned.reprojection_error,
                            cropped_aligned.accepted,
                            evidence_out,
                            cropped_aligned.compatibility,
                            cropped_aligned.cheap_evidence,
                            cropped_aligned.sift_attempted,
                        )
                        _apply_alignment_result(
                            composed_aligned,
                            "document_quad_recovery",
                            "DOCUMENT_QUAD_RECOVERY",
                        )
                        attempts[-1]["quad_area_ratio"] = quad.area_ratio
                        attempts[-1]["quad_reason"] = quad.reason
                    else:
                        if cropped_aligned.warped is not None:
                            cropped_aligned.warped.close()
                        recovery_strategies.append("DOCUMENT_QUAD_RECOVERY")
                        attempts.append(
                            {
                                "attempt": "document_quad_recovery",
                                "accepted": False,
                                "reason": "DOCUMENT_QUAD_ALIGN_FAILED",
                                "quad_area_ratio": quad.area_ratio,
                            }
                        )
                finally:
                    quad.rectified.close()
            else:
                recovery_strategies.append("DOCUMENT_QUAD_RECOVERY")
                attempts.append(
                    {
                        "attempt": "document_quad_recovery",
                        "accepted": False,
                        "reason": "DOCUMENT_QUAD_NOT_FOUND",
                    }
                )

        # Catastrophic Step 6: SuperPoint + LightGlue (local — avoids Azure $).
        if (
            not accepted
            and "LEARNED_MATCHER" not in recovery_strategies
            and (
                should_attempt_learned_matcher_any(orientation_evidence_trail)
                or (
                    evidence is not None and should_attempt_learned_matcher(evidence)
                )
            )
        ):
            from packages.recovery.azure_di_meter import learned_matcher_enabled

            if learned_matcher_enabled():
                if aligned is not None:
                    _preserve_corroboration_candidate(aligned, evidence)
                    if (
                        best_corroboration_aligned is not aligned
                        and aligned.warped is not None
                    ):
                        aligned.warped.close()
                    aligned = None
                with registration_context(
                    template_id=template.template_id, page_number=page_number
                ):
                    learned = align_learned_matcher(
                        source,
                        reference,
                        family=template.form_type.value,
                    )
                _apply_alignment_result(
                    learned,
                    "learned_matcher",
                    "LEARNED_MATCHER",
                )

        # Catastrophic Step 7: Azure DI page corners (billable — opt-in).
        if (
            not accepted
            and "AZURE_DI_PAGE_CORNERS" not in recovery_strategies
            and (
                should_attempt_document_quad_recovery_any(orientation_evidence_trail)
                or (
                    evidence is not None
                    and should_attempt_azure_di_page_corners(evidence)
                )
            )
        ):
            from packages.recovery.azure_di_meter import (
                azure_di_page_corners_enabled,
                record_azure_di_call,
            )

            if not azure_di_page_corners_enabled():
                recovery_strategies.append("AZURE_DI_PAGE_CORNERS")
                attempts.append(
                    {
                        "attempt": "azure_di_page_corners",
                        "accepted": False,
                        "reason": "AZURE_DI_PAGE_CORNERS_DISABLED_LOW_COST",
                    }
                )
            else:
                if aligned is not None:
                    _preserve_corroboration_candidate(aligned, evidence)
                    if (
                        best_corroboration_aligned is not aligned
                        and aligned.warped is not None
                    ):
                        aligned.warped.close()
                    aligned = None
                di_corners = run_azure_di_page_corners(source)
                record_azure_di_call(
                    kind="page_corners",
                    ok=di_corners.quad is not None,
                    detail=di_corners.reason,
                )
                recovery_strategies.append("AZURE_DI_PAGE_CORNERS")
                if di_corners.quad is not None:
                    quad = di_corners.quad
                    try:
                        with registration_context(
                            template_id=template.template_id, page_number=page_number
                        ):
                            cropped_aligned = align_to_reference(
                                quad.rectified,
                                reference,
                                family=template.form_type.value,
                                enforce_compatibility_precheck=False,
                            )
                        if (
                            cropped_aligned.homography is not None
                            and cropped_aligned.warped is not None
                        ):
                            import cv2
                            import numpy as np

                            composed = compose_source_to_template(
                                quad.source_to_rectified,
                                cropped_aligned.homography,
                            )
                            size = (
                                template.reference_dimensions.width_px,
                                template.reference_dimensions.height_px,
                            )
                            source_gray = np.asarray(source.convert("L"), dtype=np.uint8)
                            warped_arr = cv2.warpPerspective(
                                source_gray, composed, size, borderValue=255
                            )
                            if cropped_aligned.warped is not None:
                                cropped_aligned.warped.close()
                            evidence_out = cropped_aligned.evidence
                            if evidence_out is not None:
                                evidence_out = evidence_out.model_copy(
                                    update={
                                        "algorithm": "azure_di_corners_then_sift",
                                        "transform_matrix": composed.tolist(),
                                    }
                                )
                            composed_aligned = AlignmentResult(
                                cropped_aligned.success,
                                cropped_aligned.alignment_score,
                                cropped_aligned.good_match_count,
                                composed,
                                Image.fromarray(warped_arr),
                                "azure_di_corners_then_sift",
                                cropped_aligned.inlier_ratio,
                                cropped_aligned.reprojection_error,
                                cropped_aligned.accepted,
                                evidence_out,
                                cropped_aligned.compatibility,
                                cropped_aligned.cheap_evidence,
                                cropped_aligned.sift_attempted,
                            )
                            recovery_strategies.pop()
                            _apply_alignment_result(
                                composed_aligned,
                                "azure_di_page_corners",
                                "AZURE_DI_PAGE_CORNERS",
                            )
                            attempts[-1]["quad_area_ratio"] = quad.area_ratio
                            attempts[-1]["di_reason"] = di_corners.reason
                            attempts[-1]["di_word_count"] = di_corners.word_count
                        else:
                            if cropped_aligned.warped is not None:
                                cropped_aligned.warped.close()
                            attempts.append(
                                {
                                    "attempt": "azure_di_page_corners",
                                    "accepted": False,
                                    "reason": "AZURE_DI_CORNERS_ALIGN_FAILED",
                                    "di_reason": di_corners.reason,
                                }
                            )
                    finally:
                        quad.rectified.close()
                else:
                    attempts.append(
                        {
                            "attempt": "azure_di_page_corners",
                            "accepted": False,
                            "reason": di_corners.reason,
                            "configured": di_corners.configured,
                        }
                    )

        # Content corroboration (near-miss ratio or mild perspective).
        # Independent landmark E3 check — does not soften geometric thresholds.
        if not accepted and evidence is not None and aligned is not None:
            _preserve_corroboration_candidate(aligned, evidence)

        if (
            not accepted
            and best_corroboration_aligned is not None
            and best_corroboration_evidence is not None
            and best_corroboration_aligned.warped is not None
            and best_corroboration_aligned.homography is not None
            and template.form_type == ClaimFormType.CMS1500
        ):
            boxes = _identity_boxes()
            if boxes is not None:
                content = validate_cms1500_registration_content(
                    best_corroboration_aligned.warped,
                    patient_name_box=boxes[0],
                    patient_dob_box=boxes[1],
                )
                content_ok = content.accepted
                content_reason = content.reason
                gap_now = assess_evidence_near_miss(best_corroboration_evidence)
                accept_reason = (
                    "MILD_PERSPECTIVE_CONTENT_CORROBORATED"
                    if gap_now.is_mild_perspective
                    else "NEAR_MISS_RATIO_CONTENT_CORROBORATED"
                )
                if content.accepted:
                    recovery_strategies.append(accept_reason)
                    evidence = best_corroboration_evidence.model_copy(
                        update={
                            "accepted": True,
                            "rejection_reason": None,
                        }
                    )
                    aligned = best_corroboration_aligned
                    accepted = True
                    meta = {
                        "attempt": "content_corroboration",
                        "accepted": True,
                        "alignment_confidence": evidence.alignment_confidence,
                        "reason": accept_reason,
                        "content_ok": True,
                        "content_reason": content.reason,
                        "registration_gap_class": gap_now.gap_class,
                        "geometric_near_miss_ratio": evidence.inlier_ratio,
                        "geometric_inlier_count": evidence.inlier_count,
                        "geometric_perspective": evidence.perspective_distortion,
                    }
                    attempts.append(meta)
                else:
                    attempts.append(
                        {
                            "attempt": "content_corroboration",
                            "accepted": False,
                            "alignment_confidence": (
                                best_corroboration_evidence.alignment_confidence
                            ),
                            "reason": "CONTENT_CORROBORATION_REJECTED",
                            "content_ok": False,
                            "content_reason": content.reason,
                            "registration_gap_class": gap_now.gap_class,
                        }
                    )

        if (
            best_corroboration_aligned is not None
            and best_corroboration_aligned is not aligned
            and best_corroboration_aligned.warped is not None
        ):
            best_corroboration_aligned.warped.close()

        if not accepted and evidence is not None:
            gap = assess_evidence_near_miss(evidence)
            result["registration_gap_class"] = gap.gap_class

        raw_confidence = (
            evidence.alignment_confidence if evidence is not None else (
                aligned.alignment_score if aligned is not None else 0.0
            )
        )
        evidence_confidence = evidence_grade_alignment_confidence(
            raw_confidence, accepted=accepted
        )
        result.update(
            status="SUCCESS" if accepted else "FAILED", accepted=accepted,
            reason=(
                "REGISTRATION_ACCEPTED" if accepted else _terminal_failure_reason(attempts)
            ),
            evidence=evidence.model_dump(mode="json") if evidence else None,
            compatibility=(aligned.compatibility.model_dump(mode="json")
                           if aligned and aligned.compatibility else None),
            transform_matrix=aligned.homography.tolist() if accepted and aligned else None,
            method=aligned.method if aligned else None,
            evidence_grade_alignment_confidence=evidence_confidence,
            registration_attempts=attempts,
            registration_recovery_strategies=recovery_strategies,
        )
        if content_reason and not content_ok:
            result["content_validation_reason"] = content_reason
        return result
    finally:
        reference.close()
        if aligned is not None and aligned.warped is not None:
            aligned.warped.close()



def resolve_registered_geometry(images, registration, registry):
    """Consume only an accepted transform; resolve fields on the rectified page."""
    import cv2
    import numpy as np

    from packages.geometry.engine import GeometryEngine, GeometryRequest
    from packages.geometry.models import Box, Registration

    if registration.get('accepted') is not True or registration.get('status') != 'SUCCESS':
        raise ValueError('Geometry requires successful registration')
    evidence = registration.get('evidence') or {}
    if evidence.get('accepted') is not True or evidence.get('corner_validity') is not True:
        raise ValueError('Geometry requires accepted registration evidence')
    matrix = np.asarray(registration.get('transform_matrix'), dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError('Accepted registration transform is missing or invalid')
    template = registry.get(registration['template_id'], registration['template_version'])
    page_number = registration['page_number']
    if not 1 <= page_number <= len(images):
        raise ValueError('Registered page is out of range')
    size = (template.reference_dimensions.width_px, template.reference_dimensions.height_px)
    with images[page_number - 1].convert('L') as source:
        rectified = cv2.warpPerspective(np.asarray(source), matrix, size, borderValue=255)
    # The accepted projective transform has already mapped pixels into template space.
    # Identity here is a coordinate mapping, never an estimated registration or landmark.
    mapping = Registration(True, ((1., 0., 0.), (0., 1., 0.)), None,
                           'ACCEPTED_REGISTRATION_RECTIFIED_FRAME')
    fields = []
    for field in template.field_regions:
        started = perf_counter()
        box = Box(field.x0, field.y0, field.x1, field.y1)
        result = GeometryEngine().resolve(GeometryRequest(
            rectified, (), (), box, box, accepted_mapping=mapping))
        fields.append({'field': field.field_name, 'result': asdict(result),
                       'latency_ms': (perf_counter() - started) * 1000})
        if result.reasons not in [('GEOMETRY_RESOLVED',), ('NO_FOREGROUND',)]:
            return {'type': 'GeometryResult', 'status': 'FAILED', 'fields': fields,
                    'reason': result.reasons, 'coordinate_frame': 'rectified_template_pixels'}
    return {'type': 'GeometryResult', 'status': 'SUCCESS' if fields else 'FAILED',
            'reason': 'GEOMETRY_RESOLVED' if fields else 'NO_TEMPLATE_FIELDS',
            'page_number': page_number, 'coordinate_frame': 'rectified_template_pixels',
            'source_to_geometry_transform': matrix.tolist(), 'fields': fields,
            'warnings': ['NO_FOREGROUND is an empty geometry result, not an OCR or validation decision']}

def process_one(dataset_path="dataset.yaml", *, document=None, output_root="runs",
                document_type=None):
    """Decode one entire TIFF in memory, then invoke existing runtime routing.

    This assembly stops at the first missing integration. It does not replace
    production routing, fabricate registration, or report unexecuted stages as
    successful. Later stages remain skipped until their bindings are assembled.
    """
    from workers.ocr_engine_factories import wire_package_ocr_providers

    wire_package_ocr_providers()
    output = Path(output_root) / ("application-" + uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    state = {
        "document_id": None, "page_count": 0, "fields": [],
        "status": "FAILED", "stages": {name: "SKIPPED" for name in STAGES},
        "geometry": None, "ocr": None, "ranking": None, "validators": None,
        "decision": None, "evidence": None,
        "latency_ms": {name: None for name in STAGES}, "errors": [], "warnings": [],
    }
    images = []
    stage = "load"
    from workers.page_detection.registration_telemetry import collect_traces, save_traces

    collection = collect_traces()
    traces = collection.__enter__()
    total_started = started = perf_counter()
    try:
        dataset = DatasetManager.load(dataset_path)
        state["dataset"] = dataset.describe()
        verification = dataset.verify()
        state["dataset_verification"] = verification
        if not verification["verified"]:
            raise ValueError("Registered archive integrity verification failed")
        with ZipFile(dataset.root, "r") as archive:
            entries = [entry for entry in archive.infolist() if not entry.is_dir()]
            if document is not None:
                entries = [entry for entry in entries if entry.filename == document]
            if not entries or (document is not None and len(entries) != 1):
                raise ValueError("Document selection must identify exactly one ZIP entry")
            entry = entries[0]
            payload = archive.read(entry)
        state["source"] = {"archive": str(dataset.root), "entry": entry.filename}
        state["document_id"] = sha256(payload).hexdigest()
        with Image.open(BytesIO(payload)) as image:
            if image.format != "TIFF":
                raise ValueError("Selected document is not TIFF")
            state["page_count"] = image.n_frames
            for frame in range(image.n_frames):
                image.seek(frame)
                images.append(image.convert("RGB"))
        state["pages"] = [{"page_number": index, "width": image.width,
                           "height": image.height} for index, image in enumerate(images, 1)]
        state["stages"][stage] = "SUCCESS"
        state["latency_ms"][stage] = (perf_counter() - started) * 1000
        LOGGER.info("load SUCCESS: %s, %s pages", entry.filename, len(images))

        stage = "classification"
        started = perf_counter()
        from packages.domain.enums import (
            BundleType,
            ClaimFormType,
            ClassificationMethod,
            PageRole,
        )
        from packages.templates.registry import TemplateRegistry
        from workers.page_detection.router import PageCandidateScore, PageRoutingResult
        from workers.page_detection.template_selector import TemplateSelector

        observed_lines = {}
        registry = TemplateRegistry.load_from_directory()
        # Pin templates to the active release (default extraction-v2). Do not
        # use lexicographic latest — cms1500@03 would outrank frozen @02-12
        # while the canonical registration package remains V2-only.
        from packages.release_selection import active_release_from_env
        from packages.templates.registry import TemplateNotFoundError

        release = active_release_from_env()
        try:
            cms = registry.get_for_release(ClaimFormType.CMS1500, release)
        except TemplateNotFoundError:
            cms = registry.get("cms1500", "02-12")
        try:
            ub = registry.get_for_release(ClaimFormType.UB04, release)
        except TemplateNotFoundError:
            ub = registry.latest_for_form_type(ClaimFormType.UB04)

        # Operator-supplied document type: skip full-page PSM-11 OCR used only
        # for form classification. TemplateSelector already honors document_type;
        # registration still runs geometric gates unchanged.
        if document_type in {"CMS1500", "UB04"} and len(images) == 1:
            template = cms if document_type == "CMS1500" else ub
            role = (
                PageRole.CMS1500_CLAIM_PAGE
                if document_type == "CMS1500"
                else PageRole.UB_CLAIM_PAGE
            )
            bundle = (
                BundleType.A_CMS1500_SINGLE
                if document_type == "CMS1500"
                else BundleType.C_UB_SINGLE
            )
            routing = PageRoutingResult(
                bundle_type=bundle,
                selected_page_number=1,
                template=template,
                page_roles={1: role},
                page_scores={
                    1: PageCandidateScore(
                        page_number=1,
                        method=ClassificationMethod.TRUSTED_ANCHOR_SKIP,
                        confidence=1.0,
                        reason_codes=["OPERATOR_SUPPLIED_DOCUMENT_TYPE"],
                    )
                },
                needs_review=False,
                reason_codes=["OPERATOR_SUPPLIED_DOCUMENT_TYPE", "SKIPPED_FULL_PAGE_OCR"],
            )
            state["classification"] = asdict(routing)
            state["stages"][stage] = "SUCCESS"
            state["latency_ms"][stage] = (perf_counter() - started) * 1000
            LOGGER.info("classification SUCCESS (operator document_type=%s; OCR skipped)", document_type)
        else:
            from workers.cascade.tesseract_adapter import TesseractTextExtractor
            from workers.page_detection.router import PageRoutingService

            class ClassificationTextExtractor(TesseractTextExtractor):
                def extract(self, image):
                    lines = super().extract(image)
                    observed_lines[id(image)] = lines
                    return lines

            router = PageRoutingService(
                cms,
                ub,
                text_extractor=ClassificationTextExtractor(psm=11),
                cms_reference_image=registry.load_reference_image(cms),
                ub_reference_image=registry.load_reference_image(ub),
            )
            routing = router.route(images)
            state["classification"] = asdict(routing)
            state["stages"][stage] = "SUCCESS"
            state["latency_ms"][stage] = (perf_counter() - started) * 1000
            LOGGER.info("classification SUCCESS")
        stage = "template_selection"
        started = perf_counter()
        selection = TemplateSelector(registry).select(
            images, text_lines={page: observed_lines.get(id(image), [])
                                for page, image in enumerate(images, 1)},
            document_type=document_type,
        )
        state["template_selection"] = asdict(selection)
        state["stages"][stage] = "SUCCESS" if selection.template_id else "UNAVAILABLE"
        state["latency_ms"][stage] = (perf_counter() - started) * 1000
        LOGGER.info("template_selection %s: %s", state["stages"][stage], selection.reason)
        stage = "registration"
        started = perf_counter()
        state["registration"] = register_classified_document(images, routing, registry, selection)
        result = state["registration"]
        state["stages"][stage] = result["status"]
        state["latency_ms"][stage] = (perf_counter() - started) * 1000
        state["geometry"] = {"status": "SKIPPED", "reason": "STOP_AFTER_REGISTRATION"}
        state["stop_after"] = "registration"
        state["status"] = "SUCCESS" if result["accepted"] else "FAILED"
        if not result["accepted"]:
            state["errors"].append({"stage": stage, "type": "RegistrationNotAccepted",
                                    "message": result["reason"]})
        LOGGER.info("registration %s: %s", result["status"], result["reason"])
        if result['accepted']:
            stage = 'geometry'
            started = perf_counter()
            state['geometry'] = resolve_registered_geometry(images, result, registry)
            state['latency_ms'][stage] = (perf_counter() - started) * 1000
            state['stages'][stage] = state['geometry']['status']
            state['status'] = state['geometry']['status']
            state['stop_after'] = 'geometry'
            (output / 'GeometryResult.json').write_text(
                json.dumps(state['geometry'], indent=2, allow_nan=False), encoding='utf-8')
            (output / 'geometry_telemetry.json').write_text(json.dumps({
                'stage': stage, 'status': state['status'], 'latency_ms': state['latency_ms'][stage],
                'registration_reference': 'registration_trace.json',
                'result_reference': 'GeometryResult.json', 'ocr_executed': False,
                'registration_evidence': result['evidence'],
                'source': state['source'], 'document_id': state['document_id'],
            }, indent=2), encoding='utf-8')

    except Exception as exc:  # noqa: BLE001 -- persist state before exiting nonzero
        unavailable = isinstance(exc, (ImportError, FileNotFoundError, NotImplementedError))
        state["stages"][stage] = "UNAVAILABLE" if unavailable else "FAILED"
        state["latency_ms"][stage] = (perf_counter() - started) * 1000
        state["errors"].append({"stage": stage, "type": type(exc).__name__, "message": str(exc)})
        LOGGER.error("%s %s: %s", stage, state["stages"][stage], exc)
    finally:
        for image in images:
            image.close()
        state["latency_ms"]["total"] = (perf_counter() - total_started) * 1000
        collection.__exit__(None, None, None)
        state["registration_trace"] = {"type": "RegistrationTrace", "traces": [trace.snapshot() for trace in traces]}
        try:
            save_traces(traces, output)
        except OSError:
            LOGGER.exception("Registration trace could not be written")
        (output / "document.json").write_text(
            json.dumps(state, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8",
        )
        try:
            from workers.page_detection.template_discovery import write_report

            write_report(state, output)
        except Exception:
            LOGGER.exception("Template discovery report could not be written")
        try:
            from workers.page_detection.registration_diagnostics import (
                write_report as write_registration_report,
            )

            write_registration_report(state, output)
        except Exception:
            LOGGER.exception("Registration report could not be written")
    return output / "document.json", state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="dataset.yaml")
    parser.add_argument("--document", help="Exact ZIP entry; default is first document")
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--document-type", choices=("CMS1500", "UB04", "UNSTRUCTURED"),
                        help="Explicit operator-supplied document type; never inferred from filename")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path, state = process_one(args.dataset, document=args.document, output_root=args.output_root,
                              document_type=args.document_type)
    print(path.resolve())
    return 0 if state["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
