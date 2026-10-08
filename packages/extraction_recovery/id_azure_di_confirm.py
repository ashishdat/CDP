"""Bounded independent identifier acquisition; never grants field acceptance."""
import os
from PIL import Image
from packages.ocr.observed_confidence import observed_confidence


def maybe_confirm_id_with_azure_di(row, *, image: Image.Image, engine=None):
    updated=dict(row)
    if str(row.get('field') or '').casefold() != 'insured_id_number':return updated
    if (os.environ.get('CDP_AZURE_DI_ID_CONFIRM') or '1').lower() in {'0','false','no','off'}:return updated
    if (row.get('id_di_confirmation') or {}).get('attempted'):return updated
    from packages.extraction_recovery.cloud_stop_ladder import id_locals_settled
    if id_locals_settled(row.get('candidates')):return updated
    if any('azure_document_intelligence' in str(c.get('engine','')) for c in row.get('candidates',[])):return updated
    box=tuple(row.get('ocr_region') or row.get('canonical_region') or ())
    if len(box) != 4 or not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):return updated
    from packages.azure_di_contracts import azure_document_intelligence_configured,build_azure_read_engine
    from packages.settings import get_settings
    if engine is None:
        cfg=get_settings()
        if not azure_document_intelligence_configured(cfg):return updated
        try:engine=build_azure_read_engine(cfg)
        except Exception as exc:
            updated['id_di_confirmation']={'attempted':False,'reason':f'ID_DI_FACTORY_ERROR:{type(exc).__name__}'}
            return updated
    from packages.ocr.contracts import OCRRequest
    from packages.domain.common import BoundingBox
    from packages.domain.enums import ClaimFormType,FieldCriticality
    updated['id_di_confirmation']={'attempted':True,'observation_bbox':box}
    crop=image.crop(box).convert('RGB')
    scale=max(1,160/crop.width,64/crop.height)
    if scale > 1:crop=crop.resize((round(crop.width*scale),round(crop.height*scale)))
    request=OCRRequest(document_id='member-id-di-confirm',page_number=1,field_name='insured_id_number',
        field_type='code',form_type=ClaimFormType.CMS1500,image=crop,
        bounding_box=BoundingBox(x0=0,y0=0,x1=crop.width,y1=crop.height,image_width=crop.width,image_height=crop.height),
        criticality=FieldCriticality.CRITICAL,scope='FIELD_CROP')
    try:
        readings=engine.recognize(request)
        from packages.recovery.azure_di_meter import record_azure_di_call
        record_azure_di_call(kind='id_crop',field_name='insured_id_number',ok=bool(readings),detail='ok' if readings else 'empty')
    except Exception as exc:
        updated['id_di_confirmation']['reason']=f'ID_DI_ERROR:{type(exc).__name__}'
        return updated
    finally:crop.close()
    if not readings:
        updated['id_di_confirmation']['reason']='ID_DI_EMPTY'
        return updated
    lead=readings[0]
    raw=str(getattr(lead,'raw_value',None) or getattr(lead,'value',None) or '')
    confidence=observed_confidence(getattr(lead,'raw_confidence',None))
    from packages.extraction_recovery.span_selection import _member_id_from
    value=_member_id_from(raw)
    updated['id_di_confirmation'].update(raw_text=raw,raw_confidence=confidence,
        reason='ID_DI_OBSERVED' if value else 'ID_DI_UNSHAPED')
    if not value:return updated
    candidate={'value':value,'raw_value':raw,'engine':'azure_document_intelligence_read',
        'model_name':getattr(lead,'model_name','prebuilt-read'),'model_version':getattr(lead,'model_version','unknown'),
        'preprocessing_variant':'id_azure_di_confirm','raw_confidence':confidence or 0.0,
        'calibrated_confidence':None,'latency_ms':0.0,
        'bounding_box':dict(zip(('x0','y0','x1','y1'),box),image_width=image.width,image_height=image.height)}
    updated['candidates']=[*(row.get('candidates') or []),candidate]
    updated['status']='CANDIDATES_OBSERVED'
    return updated
