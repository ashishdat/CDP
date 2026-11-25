"""Complete local generic-layout extraction with canonical runtime decisions."""
from collections import defaultdict

from packages.claim_decision.contracts import ClaimDecisionContext
from packages.evidence_decision.contracts import (
    DecisionContext,
    FieldDecision,
    FieldDisposition,
    NextAction,
)
from packages.layout_intelligence import BundleDLayoutEngine
from packages.ocr.contracts import OCRCandidate
from packages.runtime_profile import DecisionServiceFactory
from workers.unstructured_extraction.uat_inline import recover_inline
from workers.unstructured_extraction.uat_validation import valid_scalar


class LocalLayoutCompletion:
    """Collect all page evidence before deciding a document; never guess its schema."""

    def __init__(self, *, profile_path=None, labels_path=None):
        self.uat_labels = bool(labels_path and 'uat_' in str(labels_path))
        self.layout = BundleDLayoutEngine(labels_path) if labels_path else BundleDLayoutEngine()
        self.services = (DecisionServiceFactory.from_profile(profile_path) if profile_path
                         else DecisionServiceFactory.from_profile())

    def extract_page(self, lines, *, page_number, width, height, engine, document_family=None):
        result = self.layout.extract(lines, page_number=page_number, width=width,
                                     height=height, engine=engine)
        if not self.uat_labels:
            return result
        fields=self.layout.labels.fields
        kind=(document_family or '').removeprefix('UAT_')
        if kind in {'PATH','MER','ECG','TMT'}:
            fields={**fields,'patient_name':{**fields['patient_name'],
                'aliases':[*fields['patient_name']['aliases'],'name']}}
        if kind=='TMT':
            fields={**fields,'tmt_interpretation':{**fields['tmt_interpretation'],
                'aliases':[*fields['tmt_interpretation']['aliases'],'impression','impressions','interpretation']}}
        return recover_inline(result,fields)

    def complete(self, document_id, pages, *, document_family=None, type_verified=False):
        if not pages:
            raise ValueError('At least one extracted page is required')
        families = {page.schema_evidence.schema_family for page in pages}
        family = document_family or (next(iter(families)) if len(families) == 1 else 'UNKNOWN')
        # Schema inference is not a business acceptance contract. Require an
        # explicit mandatory-field policy before allowing a touchless result.
        required = self.services.field_policy.required_fields(family)
        candidates = defaultdict(list)
        metadata={}
        for page_number, page in enumerate(pages, 1):
            actual_page=(page.lines[0].tokens[0].page_number if getattr(page,'lines',[]) and page.lines[0].tokens else page_number)
            for name, items in page.candidates.items():
                name = self.services.field_policy.canonical_name(family, name)
                for item in items:
                    tokens = [token for line in getattr(page, 'lines', []) for token in line.tokens
                        if item.bbox.x0 <= (token.bbox.x0 + token.bbox.x1)/2 <= item.bbox.x1
                        and item.bbox.y0 <= (token.bbox.y0 + token.bbox.y1)/2 <= item.bbox.y1]
                    confidence = min((token.confidence or 0 for token in tokens), default=0)
                    reference=f'page:{actual_page}:{name}:candidate:{len(candidates[name])}:layout:{item.relationship_evidence.relationship}'
                    relationship=item.relationship_evidence
                    binding=('DIRECT_LABEL' if relationship.relationship=='EXPLICIT_INLINE_LABEL_VALUE'
                        else 'BOUNDED_BELOW_LABEL' if relationship.same_column and
                        relationship.vertical_distance<=3*max(1,relationship.label_bbox.y1-relationship.label_bbox.y0)
                        and item.mapping_confidence>=.95 else 'WEAK_LABEL_GUESS')
                    metadata[reference]={'page_number':actual_page,
                        'field_association':binding,'label':item.original_label,
                        'matched_alias':item.matched_alias,'relationship':relationship.relationship}
                    candidates[name].append(OCRCandidate(
                        value=item.value, raw_value=item.value, engine=page.engine,
                        model_name=page.engine, model_version='unreported',
                        preprocessing_variant='prepared_full_page',
                        raw_confidence=confidence, calibrated_confidence=None,
                        bounding_box=item.bbox, latency_ms=0,
                        validation_results=(item.relationship_evidence.relationship,),
                        evidence_reference=reference,
                    ))
        decisions = []
        for name in sorted(set(candidates) | set(required)):
            policy = self.services.field_policy.for_field(family, name)
            if family.startswith('UAT_') and name.endswith('_verified'):
                decisions.append(FieldDecision(field_name=name,
                    disposition=FieldDisposition.HUMAN_REVIEW_REQUIRED,
                    calibrated_probability=0, next_action=NextAction.HUMAN_REVIEW,
                    reason_codes=['VERIFICATION_PROVIDER_NOT_CONFIGURED'],
                    missing_evidence=['VERIFIED_PROVIDER_RESULT'],
                    policy_version=self.services.evidence_decision.policy_version,
                    criticality=policy.criticality, required=policy.required,
                    blocks_stp=policy.blocks_stp,
                    requires_review_when_unresolved=policy.requires_review_when_unresolved,
                    **self.services.evidence_decision.configuration_identity))
                continue
            valid_candidates = [candidate for candidate in candidates[name]
                if family.startswith('UAT_') and valid_scalar(name, candidate.value or '')]
            # Validate the entire candidate set. Do not let one valid alternative
            # confer format evidence on a conflicting invalid candidate.
            format_valid = bool(valid_candidates) and len(valid_candidates) == len(candidates[name])
            decisions.append(self.services.evidence_decision.decide(DecisionContext(
                field_name=name, document_family=family, criticality=policy.criticality,
                required=policy.required, blocks_stp=policy.blocks_stp,
                requires_review_when_unresolved=policy.requires_review_when_unresolved,
                candidates=candidates[name],
                # Label proximity and datatype syntax do not establish hard
                # validation or independent corroboration.
                hard_validation_passed=format_valid,
                deterministic_evidence={'DATATYPE_VALID'} if format_valid else set(),
                deterministic_evidence_version='uat-scalar-format-v1' if format_valid else None,
            )))
        reasons = []
        if not required:
            reasons.append('DOCUMENT_ACCEPTANCE_SCHEMA_NOT_CONFIGURED')
        if not candidates:
            reasons.append('NO_EXTRACTED_FIELDS')
        if document_family and not type_verified:
            reasons.append('DOCUMENT_TYPE_UNVERIFIED')
        if not document_family and (family in {'UNKNOWN', 'NON_CLAIM'} or len(families) != 1):
            reasons.append('DOCUMENT_SCHEMA_UNRESOLVED')
        claim = self.services.claim_decision.decide(ClaimDecisionContext(
            claim_id=document_id, document_family=family, field_decisions=decisions,
            structural_consistency_valid=not reasons,
        ))
        return {
            'document_id': document_id, 'document_family': family,
            'claim_decision': claim.model_dump(mode='json'),
            'field_decisions': [decision.model_dump(mode='json') for decision in decisions],
            'extracted_candidates': {name: [{'value': c.value, 'engine': c.engine,
                'raw_confidence': c.raw_confidence, 'evidence_reference': c.evidence_reference,
                **metadata[c.evidence_reference],
                'bounding_box': c.bounding_box.model_dump(mode='json')} for c in values]
                for name, values in candidates.items() if values},
            'completion_reason_codes': reasons,
            'extraction_status': 'COMPLETED',
        }
