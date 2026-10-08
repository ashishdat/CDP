from PIL import Image
from packages.templates.registry import TemplateRegistry
from packages.extraction_recovery.ub04_registered import extract_registered_ub04


def test_local_renderer_stretch_requires_verified_print_and_recheck():
    registry=TemplateRegistry.load_from_directory();template=registry.get('ub04','2014-public-v2')
    reference=registry.load_reference_image(template);image=reference.copy()
    patch=reference.crop((1320,1320,1660,1390))
    image.paste(patch.resize((350,70)),(1320,1320))
    geometry={'status':'SUCCESS','coordinate_frame':'rectified_template_pixels','fields':[
        {'field':r.field_name,'result':{'aligned_roi':{k:getattr(r,k) for k in ('x0','y0','x1','y1')}}}
        for r in template.field_regions]}
    seen=[]
    rows,_,_=extract_registered_ub04(image,geometry,template,reference,
        lambda name,box,kind:(seen.append((name,box)) or [],[],'OBSERVED'))
    provider=next(r for r in rows if r['field'] == 'provider_npi')
    assert provider['local_alignment']['reason'] == 'LOCAL_CELL_AFFINE_VERIFIED'
    assert provider['local_alignment']['corrected_cell_frame']['accepted']
    assert provider['ocr_region'] != provider['canonical_region']
    assert ('provider_npi',tuple(provider['ocr_region'])) in seen
    assert not provider['cascade']['accepted']
