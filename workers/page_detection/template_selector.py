"""Conservative template/page selection using existing matching implementations."""

from dataclasses import asdict, dataclass, replace
import hashlib
from math import isfinite
from time import perf_counter

from packages.domain.enums import ClaimFormType
from workers.page_detection.anchor_matching import verify_anchors
from workers.page_detection.grid_signature import compute_grid_signature, signature_similarity
from workers.page_detection.registration_telemetry import registration_context
from workers.page_detection.router import (
    ALIGNMENT_CONFIDENT_THRESHOLD,
    ANCHOR_CONFIDENT_THRESHOLD,
    GRID_CONFIDENT_THRESHOLD,
)
from workers.page_detection.template_alignment import (
    DEFAULT_REGISTRATION_POLICY,
    align_to_reference,
)


@dataclass(frozen=True)
class TemplateSelection:
    template_id: str | None
    confidence: float
    reason: str
    candidate_templates: list[dict]
    template_version: str | None = None
    page_number: int | None = None


class TemplateSelector:
    """All candidates at a tier must be considered before accepting a winner.

    Thresholds reuse the existing routing policy. Multiple qualifying template/
    version/page pairs are ambiguous, even if their scores differ. An explicit
    family narrows candidates; it cannot guess a page in a multipage document.
    OCR lines must be supplied from classification; this selector never runs OCR.
    """

    def __init__(self, registry):
        self.registry = registry

    @staticmethod
    def _preferred_template_versions() -> dict[str, str]:
        """Pin collapse to the active release (default extraction-v2 → cms1500@02-12).

        Lexicographic ``latest`` would prefer ``03`` over ``02-12`` while the
        canonical registration package remains V2-only, causing false
        DISCOVERY/geometry failures. Explicit release selection overrides.
        """
        try:
            from packages.release_freeze import load_release_manifest
            from packages.release_selection import active_release_from_env

            manifest = load_release_manifest(active_release_from_env())
            versions = manifest.get("template_versions") or {}
            return {str(k): str(v) for k, v in versions.items()}
        except (OSError, KeyError, TypeError, ValueError, AttributeError):
            return {"cms1500": "02-12", "ub04": "2014"}

    @classmethod
    def _choose(cls, candidates, scores, reason):
        if len(scores) > 1:
            # Dual-loaded release templates (e.g. CMS-1500 v02-12 + v03) share
            # anchors/pages. Collapse same template_id+page to the release-pinned
            # version (not lexicographic latest) before declaring ambiguity.
            preferred = cls._preferred_template_versions()
            collapsed: dict[tuple[str, int | None], tuple[dict, float]] = {}
            for candidate, score in scores:
                key = (candidate["template_id"], candidate.get("page_number"))
                previous = collapsed.get(key)
                if previous is None:
                    collapsed[key] = (candidate, score)
                    continue
                want = preferred.get(candidate["template_id"])
                prev_ver = previous[0]["template_version"]
                cur_ver = candidate["template_version"]
                if want is not None:
                    if cur_ver == want and prev_ver != want:
                        collapsed[key] = (candidate, score)
                    # else keep previous (already preferred or neither matches)
                elif cur_ver > prev_ver:
                    collapsed[key] = (candidate, score)
            scores = list(collapsed.values())
        if len(scores) > 1:
            return TemplateSelection(None, max(score for _, score in scores),
                                     "AMBIGUOUS_TEMPLATE", candidates)
        if scores:
            candidate, score = scores[0]
            return TemplateSelection(candidate["template_id"], score, reason, candidates,
                                     candidate["template_version"], candidate["page_number"])
        return None

    def select(self, images, *, text_lines, document_type=None):
        roles = {}
        families = {}
        templates = sorted(
            (template for family in ClaimFormType
             for template in self.registry.all_for_form_type(family)),
            key=lambda template: (template.template_id, template.version),
        )
        if document_type is not None:
            templates = [template for template in templates
                         if template.form_type.value == document_type]
            if not templates:
                return TemplateSelection(None, 0.0, "UNKNOWN_DOCUMENT_TYPE", [])
        pairs = [(template, page, image) for template in templates
                 for page, image in enumerate(images, 1)]
        if document_type is None:
            import re

            from packages.recovery.independent_failures import (
                NON_CLAIM_CANDIDATES,
                PageRole,
                classify_page_text,
            )
            texts = {page: "\n".join(
                str(getattr(line, "text", line)) for line in text_lines.get(page, [])
            ) for page in range(1, len(images) + 1)}
            roles = {page: classify_page_text(text) for page, text in texts.items()}
            for page, text in texts.items():
                if (re.search(r"UB[- ]?04|CMS[- ]?1450", text, re.IGNORECASE) and
                        re.search(r"CMS[- ]?1500|NUCC|HEALTH INSURANCE CLAIM", text, re.IGNORECASE)):
                    roles[page] = PageRole.UNKNOWN  # Preserve mixed-family ambiguity.
            families = {PageRole.CMS1500: "CMS1500", PageRole.UB04: "UB04"}
            has_claim_page = any(role in families for role in roles.values())
            # Cover signatures may exclude a page from geometry only when a
            # separate claim page is positively identified in the same bundle.
            # All original pages remain available as bundle attachments.
            pairs = [(template, page, image) for template, page, image in pairs
                     if (roles[page] not in families or
                         template.form_type.value == families[roles[page]])
                     and not (has_claim_page and roles[page] in NON_CLAIM_CANDIDATES)]
        candidates = [{"template_id": template.template_id, "template_version": template.version,
                       "page_number": page, "scores": {}, "reasons": []}
                      for template, page, _ in pairs]
        if document_type is not None and len(images) == 1:
            return self._choose(candidates, [(candidate, 1.0) for candidate in candidates],
                                "EXPLICIT_DOCUMENT_TYPE") or TemplateSelection(
                                    None, 0.0, "NO_CANDIDATES", candidates)
        scores = []
        for candidate, (template, page, _) in zip(candidates, pairs, strict=True):
            anchors = verify_anchors(text_lines.get(page, []), template.anchor_definitions)
            qualification = anchors.required_confidence if anchors.required_confidence is not None else anchors.confidence
            candidate["scores"]["anchors"] = qualification
            candidate["diagnostics"] = {
                "anchor_count": len(template.anchor_definitions),
                "matched_anchor_count": len(anchors.matched_phrases),
                "matched_anchor_phrases": list(anchors.matched_phrases),
                "expected_anchors": [anchor.phrase for anchor in template.anchor_definitions],
                "missing_required_anchors": list(anchors.missing_required),
                "all_anchor_confidence": anchors.confidence,
                "required_anchor_confidence": qualification,
                "thresholds": {"anchors": ANCHOR_CONFIDENT_THRESHOLD,
                               "features": GRID_CONFIDENT_THRESHOLD,
                               "registration": ALIGNMENT_CONFIDENT_THRESHOLD},
            }
            if anchors.all_required_matched and qualification >= ANCHOR_CONFIDENT_THRESHOLD:
                scores.append((candidate, qualification))
        selected = self._choose(candidates, scores, "ANCHOR_MATCH")
        if selected:
            return selected
        references = {}
        try:
            scores = []
            for candidate, (template, _, image) in zip(candidates, pairs, strict=True):
                key = (template.template_id, template.version)
                if key not in references:
                    references[key] = self.registry.load_reference_image(template)
                reference = references[key]
                if reference is None:
                    candidate["reasons"].append("REFERENCE_TEMPLATE_IMAGE_UNAVAILABLE")
                    continue
                score = signature_similarity(compute_grid_signature(image),
                                             compute_grid_signature(reference))
                candidate["scores"]["features"] = score if isfinite(score) else None
                if isfinite(score) and score >= GRID_CONFIDENT_THRESHOLD:
                    scores.append((candidate, score))
            selected = self._choose(candidates, scores, "FEATURE_MATCH")
            if selected:
                return selected
            scores = []
            probe_started = perf_counter()
            probe_cache = {}
            for candidate, (template, _, image) in zip(candidates, pairs, strict=True):
                if perf_counter() - probe_started >= 60:
                    # Unexamined pages are unknown, never negative evidence.
                    # Do not accept a partial winner when bundle ambiguity
                    # could remain among the unexamined candidates.
                    return TemplateSelection(None, 0.0, 'TEMPLATE_PROBE_BUDGET_EXHAUSTED', candidates)
                reference = references[(template.template_id, template.version)]
                if reference is None:
                    continue
                probe_key = (candidate["page_number"], template.form_type.value,
                             reference.mode, reference.size,
                             hashlib.sha256(reference.tobytes()).hexdigest())
                cached = probe_cache.get(probe_key)
                if cached is not None:
                    result, bypassed = cached
                    candidate["diagnostics"]["equivalent_reference_probe_reused"] = True
                    if bypassed:
                        candidate["diagnostics"]["lineage_precheck_bypass"] = True
                else:
                    with registration_context(template_id=template.template_id, page_number=candidate["page_number"]):
                        result = align_to_reference(image, reference, family=template.form_type.value,
                                                    enforce_compatibility_precheck=True, allow_recovery=False)
                        # Ops ladder offers LINEAGE_PRECHECK_BYPASS after selection.
                        # Selector must soft-retry lineage misses so CMS pages that
                        # fail only the cheap lineage gate still reach registration.
                        lineage_miss = (
                            not result.accepted
                            and result.evidence is not None
                            and "template_lineage_mismatch"
                            in str(result.evidence.rejection_reason or "")
                        )
                        if lineage_miss:
                            if result.warped is not None:
                                result.warped.close()
                            result = align_to_reference(
                                image,
                                reference,
                                family=template.form_type.value,
                                enforce_compatibility_precheck=False, allow_recovery=False,
                            )
                            candidate["diagnostics"]["lineage_precheck_bypass"] = True
                    # Cache only measurements, never an owned warped image.
                    probe_cache[probe_key] = (
                        replace(result, warped=None),
                        bool(candidate["diagnostics"].get("lineage_precheck_bypass")),
                    )
                try:
                    score = result.alignment_score
                    candidate["scores"]["registration"] = score if isfinite(score) else None
                    compatible = (result.compatibility is not None
                                  and result.compatibility.status.value != "INCOMPATIBLE")
                    # After lineage bypass, cheap compatibility may still say
                    # INCOMPATIBLE — geometric gates alone decide acceptance.
                    lineage_bypassed = bool(
                        candidate["diagnostics"].get("lineage_precheck_bypass")
                    )
                    if lineage_bypassed:
                        compatible = True
                    candidate["diagnostics"].update(
                        registration_policy=asdict(DEFAULT_REGISTRATION_POLICY),
                        cheap_registration_evidence=(result.cheap_evidence.model_dump(mode="json")
                            if result.cheap_evidence is not None and result.cheap_evidence is not result.evidence
                            else None),
                        matched_features=result.good_match_count,
                        homography_score=(result.evidence.homography_quality
                                          if result.evidence else None),
                        registration_evidence=(result.evidence.model_dump(mode="json")
                                               if result.evidence else None),
                        registration_gates_passed=bool(
                            result.success and result.accepted and compatible and result.evidence
                            and result.evidence.accepted and result.evidence.corner_validity),
                    )
                    if (result.success and result.accepted and compatible and result.evidence
                            and result.evidence.accepted and result.evidence.corner_validity
                            and isfinite(score) and score >= ALIGNMENT_CONFIDENT_THRESHOLD):
                        scores.append((candidate, score))
                finally:
                    if result.warped is not None:
                        result.warped.close()
            accepted = self._choose(candidates, scores, "REGISTRATION_CONFIDENCE")
            if accepted is not None:
                return accepted
            near_misses=[]
            for candidate in candidates:
                evidence=candidate.get("diagnostics",{}).get("registration_evidence") or {}
                reasons=set(filter(None,str(evidence.get("rejection_reason") or "").split(",")))
                score=candidate.get("scores",{}).get("registration")
                if (reasons == {"insufficient_inliers"} and evidence.get("corner_validity")
                        and isinstance(score,(int,float)) and isfinite(score)
                        and score >= ALIGNMENT_CONFIDENT_THRESHOLD):
                    candidate["diagnostics"]["requires_full_recovery"] = True
                    near_misses.append((candidate,0.0))
            proposed=self._choose(candidates,near_misses,"GEOMETRY_NEAR_MISS_RECOVERY_CANDIDATE")
            if proposed is not None:
                return proposed  # Proposal only; full registration must pass every gate.
            # A unique positively identified claim page may enter the full
            # registration recovery ladder. This is a proposal, not accepted
            # geometry: the application still enforces every registration gate.
            hints = [(candidate, 0.0) for candidate in candidates
                     if references.get((candidate['template_id'], candidate['template_version'])) is not None
                     and families.get(roles.get(candidate['page_number'])) ==
                     self.registry.get(candidate['template_id'], candidate['template_version']).form_type.value]
            proposed = self._choose(candidates, hints, "CLAIM_FAMILY_RECOVERY_CANDIDATE")
            return proposed or TemplateSelection(
                None, 0.0, "NO_TEMPLATE_ABOVE_THRESHOLD", candidates)
        finally:
            for reference in references.values():
                if reference is not None:
                    reference.close()
