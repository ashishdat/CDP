"""UAT extraction completeness, separate from canonical claim/underwriting STP."""
import re
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from workers.unstructured_extraction.uat_validation import valid_scalar
from workers.unstructured_extraction.uat_values import DATE_FIELDS, date_value, identity_value

DEFAULT_POLICY = Path(__file__).resolve().parents[2]/'config/uat_extraction_acceptance.yaml'


def normalized(field, value, references=()):
    if field in DATE_FIELDS:
        return date_value(value,references)['canonical_value'] or value
    if field=='patient_name':
        value=re.sub(r'^(?:mrs|mr|ms|dr)(?:\.\s*|\s+)','',value,flags=re.IGNORECASE)
        return ' '.join(re.sub(r'[^a-z ]',' ',value.casefold()).split())
    return re.sub(r'[^a-z0-9]', '', value.casefold())


def type_support(pages,spec,*,kind=None,filename='',visual=None):
    matches=[]
    for number,page in enumerate(pages,1):
        text=' '.join(line.text for line in page.lines).casefold()
        words=' '.join(re.sub(r'[^a-z0-9 ]',' ',text).split())
        compact=re.sub(r'[^a-z0-9]','',text)
        for anchor in spec['required_text_anchors']:
            normal=' '.join(re.sub(r'[^a-z0-9 ]',' ',anchor).split())
            if normal in words or (len(normal.replace(' ',''))>=10 and normal.replace(' ','') in compact):
                matches.append({'page':number,'anchor':anchor,'basis':'EXPLICIT_CONTENT_ANCHOR'})
            elif not matches and kind in {'PATH','MER','ECG','TMT'} and len(normal)>=8:
                tokens=words.split();size=len(normal.split())
                best=max((SequenceMatcher(None,normal,' '.join(tokens[start:start+count])).ratio()
                    for start in range(len(tokens)) for count in {max(1,size-1),size,size+1}),default=0)
                if best>=.88:
                    matches.append({'page':number,'anchor':anchor,'basis':'FUZZY_CONTENT_ANCHOR','similarity':best})
    if kind in {'ECG','TMT'} and visual and visual.get('waveforms'):
        text=' '.join(line.text for page in pages for line in page.lines).casefold()
        stress=bool(re.search(r'bruce|treadmill|exercise\s+stress|stage\s*[1-9]',text))
        if kind=='ECG' or stress:
            matches.extend({**item,'basis':'WAVEFORM_AND_STRESS_EVIDENCE' if kind=='TMT' else 'WAVEFORM_PAGE_EVIDENCE'} for item in visual['waveforms'])
    if matches and filename and kind and re.search(r'(?<![A-Z])'+re.escape(kind)+r'(?![A-Z])',filename.upper()):
        matches.append({'filename':filename,'basis':'SUPPORTING_FILENAME_HINT'})
    return matches


def field_binding(item):
    binding=item.get('field_association')
    if not binding and ':llm_value_located_in_ocr' in item.get('evidence_reference',''):
        binding='LLM_VALUE_LOCATED_IN_OCR'
    return binding in {'DIRECT_LABEL','BOUNDED_BELOW_LABEL','LLM_VALUE_LOCATED_IN_OCR',
                       'CASE_NAME_SOURCE_MATCH','MASKED_ID_SOURCE_PATTERN','PAN_HOLDER_POSITION_AND_LABEL',
                       'SCHEMA_LABEL_BOUNDARY','CERTIFICATE_DATE_POSITION','DOCUMENT_DATE_POSITION','LICENCE_LABEL_POSITION','SCHEMA_DIAGNOSIS_COLUMN',
                       'HANDWRITTEN_CROP_CASE_NAME_MATCH'}


class ExtractionAcceptance:
    def __init__(self, policy_path=DEFAULT_POLICY):
        self.config = yaml.safe_load(Path(policy_path).read_text(encoding='utf-8'))

    def decide(self, kind, pages, *, expected_pages, assets, candidates, filename='', visual=None, known_names=(), case_verification_required=False, verified_name_sources=(), document_id=None):
        spec = self.config['profiles'].get(kind, self.config['profiles']['OTHER'])
        reasons = []
        fields = {}
        diagnostics={}
        representations={}
        if len(pages) != expected_pages or not pages:
            reasons.append('PAGE_EXTRACTION_INCOMPLETE')
        if len(assets) != expected_pages or not all(
            asset.get('sha256') and asset.get('width', 0) > 0 and asset.get('height', 0) > 0
            for asset in assets
        ):
            reasons.append('PAGE_ASSET_NOT_PERSISTED')
        support=type_support(pages,spec,kind=kind,filename=filename,visual=visual)
        if case_verification_required and kind in {'PATH','MER','ECG','TMT'} and not known_names:
            reasons.append('CASE_NAME_REFERENCE_UNAVAILABLE:patient_name')
        if spec.get('review_required'):
            reasons.append('EXTRACTION_SCHEMA_UNSUPPORTED')
        if not spec.get('asset_only'):
            if not support:
                reasons.append('DOCUMENT_CONTENT_TYPE_UNCONFIRMED')
            for field in spec['required_fields']:
                if field=='identity_number' and kind in {'AADHAAR','IDENTITY_PROOF'} and not any(
                    valid_scalar('identity_number',item.get('value','')) for item in candidates.get('identity_number',[])):
                    masked=[item for item in candidates.get('identity_number_masked',[])
                        if valid_scalar('identity_number_masked',item.get('value',''))
                        and not item.get('vision_only') and item.get('field_association')!='VISION_ONLY_CROP_PROPOSAL'
                        and item.get('last4_match_verified') and item.get('evidence_reference')
                        and field_binding(item) and item.get('mask_basis') in
                        {'EXPLICIT_EIGHT_MASK_CHARACTERS','SOLID_REDACTION_ADJACENT_TO_SUFFIX'}]
                    if masked:
                        suffixes={identity_value(item['value'])['visible_suffix'] for item in masked}
                        if len(suffixes)>1:
                            reasons.append('CONFLICTING_VALUES:identity_number_masked')
                        else:
                            best=max(masked,key=lambda item:item['raw_confidence'])
                            fields['identity_number_masked']=best
                            representations['identity_number_masked']=identity_value(best['value'])
                            if best['raw_confidence']<self.config['minimum_ocr_confidence']:
                                reasons.append('LOW_OCR_CONFIDENCE:identity_number_masked')
                        continue
                observations=[];values=[]
                for item in candidates.get(field,[]):
                    exclusions=[]
                    if not valid_scalar(field,item.get('value') or ''): exclusions.append('INVALID_FORMAT_OR_LABEL_TEXT')
                    if self.config.get('contract',{}).get('field_evidence_required') and not item.get('evidence_reference'):
                        exclusions.append('SOURCE_EVIDENCE_MISSING')
                    if self.config.get('contract',{}).get('field_binding_required') and not field_binding(item):
                        exclusions.append('WEAK_FIELD_ASSOCIATION')
                    if item.get('role_conflict'): exclusions.append('FIELD_ROLE_CONFLICT')
                    if item.get('source_reading_ambiguous'): exclusions.append('HANDWRITTEN_TRANSCRIPTION_UNCONFIRMED')
                    if item.get('vision_only') or item.get('field_association')=='VISION_ONLY_CROP_PROPOSAL':
                        exclusions.append('VISION_ONLY_ACCURACY_NOT_VALIDATED')
                    observations.append({'candidate':item,'exclusions':exclusions})
                    if not exclusions: values.append(item)
                diagnostics[field]={'observations':observations,'eligible_candidates':len(values)}
                if not values:
                    reasons.append('MISSING_OR_INVALID:' + field)
                    continue
                references=[item['value'] for item in values]
                if field in DATE_FIELDS:
                    representations[field]=[date_value(item['value'],references) for item in values]
                    if any(item['year_ambiguous'] for item in representations[field]):
                        reasons.append('AMBIGUOUS_DATE_YEAR:'+field)
                        continue
                same_case_name=False
                if field=='patient_name' and known_names and kind in {'PATH','MER','ECG','TMT'}:
                    from workers.unstructured_extraction.uat_recovery_rules import name_similarity
                    same_case_name=any(all(name_similarity(item['value'],known)>=.90 for item in values) for known in known_names)
                if len({normalized(field, item['value'],references) for item in values}) != 1 and not same_case_name:
                    reasons.append('CONFLICTING_VALUES:' + field)
                    continue
                best = max(values, key=lambda item: item['raw_confidence'])
                fields[field] = best
                if field=='patient_name' and kind in {'PATH','MER','ECG','TMT'} and known_names:
                    from workers.unstructured_extraction.uat_recovery_rules import name_similarity
                    similarity=max(name_similarity(best['value'],name) for name in known_names)
                    fields[field]={**best,'case_name_match':similarity>=.90,'case_name_similarity':similarity}
                    if similarity<.90:
                        reasons.append('CASE_NAME_MISMATCH:patient_name')
                if field in DATE_FIELDS:
                    fields[field]={**best,'date_representation':date_value(best['value'],references)}
                if field=='identity_number':
                    representation=identity_value(best['value']);representations[field]=representation
                    if representation['kind'] not in spec.get('identifier_kinds',['full_aadhaar','full_pan']):
                        reasons.append('IDENTIFIER_KIND_MISMATCH:'+field)
                    if representation['kind']=='full_aadhaar' and any(
                        item.get('last4_match_verified') and identity_value(item.get('value','')).get('visible_suffix') != representation['visible_suffix']
                        for item in candidates.get('identity_number_masked',[])):
                        reasons.append('CONFLICTING_VALUES:identity_number_masked')
                if best['raw_confidence'] < self.config['minimum_ocr_confidence']:
                    corroboration=[]
                    if field=='patient_name':
                        from workers.unstructured_extraction.uat_recovery_rules import (
                            name_similarity,
                        )
                        corroboration=[ref for ref in verified_name_sources
                            if ref.get('document_id') and ref['document_id']!=document_id
                            and ref.get('source_verified') and ref.get('raw_confidence',0)>=self.config['minimum_ocr_confidence']
                            and ref.get('evidence_reference') and name_similarity(best['value'],ref['value'])>=.90]
                    if corroboration:
                        fields[field]={**fields[field],'acceptance_basis':'OTHER_DOCUMENT_VERIFIED_NAME_MATCH',
                            'corroborating_name_sources':corroboration,'ocr_threshold_unchanged':self.config['minimum_ocr_confidence']}
                    else:
                        reasons.append('LOW_OCR_CONFIDENCE:' + field)
        if kind in {'AADHAAR','IDENTITY_PROOF'}:
            vids=[]
            for number,page in enumerate(pages,1):
                for line in page.lines:
                    for match in re.finditer(r'\bVID\s*[:：]?\s*((?:\d\s*){16})(?!\d)',line.text,re.IGNORECASE):
                        vids.append({'page':number,'value':re.sub(r'\D','',match.group(1)),
                                     'identifier_kind':'aadhaar_vid','not_aadhaar_number':True})
            if vids: representations['aadhaar_vid']=vids
            masks=[]
            for number,page in enumerate(pages,1):
                for line in page.lines:
                    for match in re.finditer(r'(?:[xX*•●#]\s*){8}\d{4}',line.text):
                        masks.append({'page':number,**identity_value(match.group())})
            if masks:
                representations['masked_identifiers']=masks
                if 'identity_number' not in fields and 'identity_number_masked' not in fields:
                    reasons=[r for r in reasons if r!='MISSING_OR_INVALID:identity_number']
                    reasons.append('FULL_IDENTIFIER_REQUIRED_SOURCE_MASKED')
        roles=[]
        if not reasons:
            if spec.get('asset_only'): roles=['image_asset']
            elif kind=='DRIVING_LICENSE': roles=['identity:any','identity:driving_license']
            elif kind in {'AADHAAR','PAN','IDENTITY_PROOF'}:
                id_kind=representations.get('identity_number',{}).get('kind','')
                if id_kind.startswith('full_'): roles=['identity:any','identity:'+id_kind.removeprefix('full_')]
                elif 'identity_number_masked' in fields: roles=['identity:any','identity:aadhaar']
            else: roles=['medical:'+kind.lower()]
        return {'policy_version': self.config['version'], 'scope': self.config['scope'],
                'document_type': kind, 'extraction_stp_eligible': not reasons,
                'disposition': 'EXTRACTION_COMPLETED' if not reasons else 'EXTRACTION_REVIEW_REQUIRED',
                'reason_codes': reasons, 'extracted_fields': fields,
                'field_diagnostics':diagnostics,'value_representations':representations,
                'vision_only_review_proposals': [item for items in candidates.values() for item in items if item.get('vision_only')],
                'document_type_evidence':support,'provided_roles':roles,
                'asset_only': bool(spec.get('asset_only')), 'correctness_verified': False}
