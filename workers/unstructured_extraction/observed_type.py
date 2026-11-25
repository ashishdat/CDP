"""Guarded portrait routing; missing OCR text alone never changes document type."""
from pathlib import Path

from workers.unstructured_extraction.uat_validation import valid_scalar


def resolve_observed_type(declared, *, records, assets, sources, candidates, policy, successful_di_pages, local_portraits=None):
    result={'declared_type':declared,'effective_type':declared,'changed':False,
            'reason_codes':[],'evidence_references':[]}
    config=policy.get('observed_type_routing',{})
    if declared not in config.get('allowed_declared_types',[]):
        return result
    if local_portraits and assets and not any(lines for _,lines in sources):
        covered={item['page'] for item in local_portraits}
        if covered=={asset['page'] for asset in assets} and not any(
            valid_scalar(name,item.get('value') or '') for name,items in candidates.items() for item in items):
            result.update(effective_type='PERSON_PHOTO',changed=True,
                reason_codes=['LOCAL_PORTRAIT_DETECTED_WITH_NO_SOURCE_TEXT'],evidence_references=local_portraits)
            return result
    # Every original page must have a successful DI record and no readable words.
    if (len(sources)!=len(assets) or not assets or any(lines for _,lines in sources)
        or set(successful_di_pages)!=set(range(1,len(assets)+1))):
        return result
    if any(valid_scalar(name,item.get('value') or '')
           for name in ['patient_name','patient_dob','identity_number']
           for item in candidates.get(name,[])):
        return result
    covered=set()
    references=[]
    for record in records:
        if record.get('status')!='SUCCESS' or not record.get('provider'):
            continue
        image=record.get('source_image')
        page=next((index for index,asset in enumerate(assets,1)
                   if image and Path(asset['path']).resolve()==Path(image).resolve()),None)
        if page is None:
            continue
        box=record.get('crop_fraction',[])
        if len(box)!=4 or not (0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1):
            continue
        if (box[2]-box[0])*(box[3]-box[1])<config['minimum_crop_coverage']:
            continue
        fields=record.get('fields',[])
        # Preserve contrary classifications and readable identity evidence.
        kinds=[field for field in fields if field.get('field_name')=='content_kind'
               and not field.get('insufficient_evidence') and field.get('value')]
        if any(field['value']!=config['content_kind'] for field in kinds):
            return result
        if any(field.get('field_name') in {'patient_name','patient_dob','identity_number'}
               and not field.get('insufficient_evidence') and field.get('value') for field in fields):
            return result
        if any(field.get('confidence',0)>=config['minimum_classification_confidence'] for field in kinds):
            covered.add(page)
            references.append(record.get('job_id',f'page:{page}'))
    if covered==set(range(1,len(assets)+1)):
        result.update(effective_type=config['effective_type'],changed=True,
            reason_codes=['PORTRAIT_CLASSIFICATION_WITH_FULL_PAGE_CROP_AND_NO_IDENTITY_TEXT'],
            evidence_references=references)
    return result
