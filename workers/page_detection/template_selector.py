"""Conservative template/page selection using existing matching implementations."""

from dataclasses import dataclass
from math import isfinite

from packages.domain.enums import ClaimFormType
from workers.page_detection.anchor_matching import verify_anchors
from workers.page_detection.grid_signature import compute_grid_signature, signature_similarity
from workers.page_detection.router import (
    ALIGNMENT_CONFIDENT_THRESHOLD,
    ANCHOR_CONFIDENT_THRESHOLD,
    GRID_CONFIDENT_THRESHOLD,
)
from workers.page_detection.template_alignment import align_to_reference


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
    def _choose(candidates, scores, reason):
        if len(scores) > 1:
            return TemplateSelection(None, max(score for _, score in scores),
                                     "AMBIGUOUS_TEMPLATE", candidates)
        if scores:
            candidate, score = scores[0]
            return TemplateSelection(candidate["template_id"], score, reason, candidates,
                                     candidate["template_version"], candidate["page_number"])
        return None

    def select(self, images, *, text_lines, document_type=None):
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
            candidate["scores"]["anchors"] = anchors.confidence
            candidate["diagnostics"] = {
                "anchor_count": len(template.anchor_definitions),
                "matched_anchor_count": len(anchors.matched_phrases),
                "missing_required_anchors": list(anchors.missing_required),
                "thresholds": {"anchors": ANCHOR_CONFIDENT_THRESHOLD,
                               "features": GRID_CONFIDENT_THRESHOLD,
                               "registration": ALIGNMENT_CONFIDENT_THRESHOLD},
            }
            if anchors.all_required_matched and anchors.confidence >= ANCHOR_CONFIDENT_THRESHOLD:
                scores.append((candidate, anchors.confidence))
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
            for candidate, (template, _, image) in zip(candidates, pairs, strict=True):
                reference = references[(template.template_id, template.version)]
                if reference is None:
                    continue
                result = align_to_reference(image, reference, family=template.form_type.value,
                                            enforce_compatibility_precheck=True)
                try:
                    score = result.alignment_score
                    candidate["scores"]["registration"] = score if isfinite(score) else None
                    compatible = (result.compatibility is not None
                                  and result.compatibility.status.value != "INCOMPATIBLE")
                    candidate["diagnostics"].update(
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
            return self._choose(candidates, scores, "REGISTRATION_CONFIDENCE") or TemplateSelection(
                None, 0.0, "NO_TEMPLATE_ABOVE_THRESHOLD", candidates)
        finally:
            for reference in references.values():
                if reference is not None:
                    reference.close()
