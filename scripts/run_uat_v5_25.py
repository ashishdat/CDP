"""Local orientation and source binding replay; only name crops may call cloud."""
import argparse
import copy
import hashlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from packages.ocr.tesseract_adapter import TesseractTextExtractor
from packages.ocr.text_extraction import TextLine
from scripts import run_uat_all as batch
from scripts.run_uat_v4_25 import pages_for, reconcile
from scripts.test_uat_subset import prepare as clone_subset
from workers.unstructured_extraction.uat_recovery_rules import masked_candidates, name_similarity
from workers.unstructured_extraction.uat_rotation import crop_fraction, rotation_angle, transform_di


def rebuild(record):
    directory=Path(record['directory']);local=batch.read(directory/'local.json')
    old_assets=copy.deepcopy(local['assets']);assets=[];layouts=[];paths=[];rotations=[]
    for old in old_assets:
        number=old['page'];di_path=directory/f'di_page_{number:03d}.json'
        di=batch.read(di_path) if di_path.exists() else {}
        angle=rotation_angle(di)
        asset=copy.deepcopy(old)
        if angle:
            with Image.open(old['path']) as source:
                image=source.convert('RGB').rotate(angle,expand=True)
            target=directory/f'page_oriented_{number:03d}.png';image.save(target)
            asset.update(path=str(target.resolve()),width=image.width,height=image.height,
                         sha256=hashlib.sha256(target.read_bytes()).hexdigest(),original_page_path=old['path'],rotation=angle)
            lines=TesseractTextExtractor(psm=11).extract(image);image.close()
            transformed=transform_di(di,old,angle);transformed['source_image']=asset['path'];batch.write(di_path,transformed)
            batch.write(target.with_suffix('.json'),{'asset':asset,'ocr_lines':[vars(line) for line in lines]})
            for path in directory.glob('llm_*.json'):
                llm=batch.read(path)
                if llm.get('source_image') and Path(llm['source_image']).resolve()==Path(old['path']).resolve():
                    llm['original_source_image']=llm['source_image'];llm['source_image']=asset['path']
                    llm['original_crop_fraction']=llm['crop_fraction']
                    llm['crop_fraction']=crop_fraction(llm['crop_fraction'],old['width'],old['height'],angle)
                    llm['rotation_rebased_without_cloud_call']=angle;batch.write(path,llm)
            rotations.append({'page':number,'angle':angle,'original':old['path'],'oriented':asset['path']})
        else:
            raw=batch.read(Path(old['path']).with_suffix('.json'))
            lines=[TextLine(**line) for line in raw['ocr_lines']]
        layout=batch.SERVICE.extract_page(lines,page_number=number,width=asset['width'],height=asset['height'],
            engine='tesseract_psm_11',document_family=record['declared_type'])
        path=directory/f'layout_v5_{number:03d}.json';path.write_text(layout.model_dump_json(),encoding='utf-8')
        assets.append(asset);layouts.append(layout);paths.append(str(path))
    fields=batch.SERVICE.complete(record['sha256'],layouts,document_family='UAT_'+record['declared_type'],type_verified=True)
    local.update(assets=assets,layouts=paths,candidates=fields['extracted_candidates'],stage='LOCAL',rotations=rotations)
    local['decision']=batch.ACCEPT.decide(record['declared_type'],layouts,expected_pages=record['pages'],assets=assets,candidates=local['candidates'])
    batch.write(directory/'local.json',local)
    (directory/'visual_evidence.json').unlink(missing_ok=True)
    record.update(apply_recovery_v4=True,apply_recovery_v5=True)
    record.pop('masked_candidates',None)
    if record['declared_type'] in {'AADHAAR','IDENTITY_PROOF'}:
        record['masked_candidates']=masked_candidates(assets,pages_for(local))
    return record


def prepare(source,output,resume=False):
    if not resume:clone_subset(source,output,25)
    output=Path(output).resolve()
    records=batch.read(output/'inventory.json')
    if not resume:
        with ThreadPoolExecutor(max_workers=4) as pool:
            records=list(pool.map(rebuild,records))
    batch.write(output/'inventory.json',records)
    bycase=defaultdict(list);first=[]
    for index,record in enumerate(records,1):
        doc=batch.evaluate(record,final=True);first.append(doc)
        field=doc['decision'].get('extracted_fields',{}).get('patient_name')
        if (field and field.get('raw_confidence',0)>=.8 and field.get('evidence_reference')
            and 'CASE_NAME_MISMATCH:patient_name' not in doc['decision']['reason_codes']):
            bycase[record['case_id']].append({**field,'document_id':record['id'],'source_verified':True,
                'verification_basis':'HIGH_CONFIDENCE_SOURCE_BOUND_NAME_OTHER_DOCUMENT',
                'identity_document':doc['effective_type'] in {'PAN','AADHAAR','IDENTITY_PROOF','DRIVING_LICENSE'}})
        if index%25==0:print('Initial binding',index,'/',len(records),flush=True)
    contexts={}
    for case,items in bycase.items():
        groups=[]
        for item in items:
            group=next((g for g in groups if all(name_similarity(item['value'],x['value'])>=.90 for x in g)),None)
            if group is None:groups.append([item])
            else:group.append(item)
        groups.sort(key=lambda g:(sum(x['identity_document'] for x in g),len(g)),reverse=True)
        # An unresolved tie cannot establish a verified case name.
        rank=lambda g:(sum(x['identity_document'] for x in g),len(g))
        contexts[case]=groups[0] if len(groups)==1 or rank(groups[0])>rank(groups[1]) else []
    for record in records:
        refs=[item for item in contexts.get(record['case_id'],[]) if item['document_id']!=record['id']]
        record['verified_name_sources']=refs
        record['case_known_names']=sorted({item['value'] for item in refs})
    batch.write(output/'case_name_context_v5.json',contexts)
    batch.write(output/'inventory.json',records)
    reconcile(output,prepare_handwriting=False)
    # Locate name-specific fields on oriented pages. Existing identical crops
    # are not repeated; only previously unresolved handwritten-name regions.
    jobs=[]
    for record in records:
        doc=batch.read(Path(record['directory'])/'final.json')
        if doc['effective_type'] not in {'MER','ECG','TMT'} or not any(
            reason.endswith(':patient_name') for reason in doc['decision']['reason_codes']):continue
        for asset in doc['assets']:
            if doc['effective_type']=='MER' and asset['page']>3:continue
            if doc['effective_type']=='TMT' and asset['page'] not in {1,record['pages']}:continue
            regions=[('upper',[.01,.01,.99,.50])]
            if doc['effective_type']=='ECG':regions.append(('lower',[.01,.50,.99,.99]))
            for role,box in regions:
                target=Path(record['directory'])/f"llm_p{asset['page']:03d}_v5_handwritten_name_{role}.json"
                jobs.append({'id':record['id']+'/handwritten_name/'+str(asset['page'])+'/'+role,
                    'image':asset['path'],'crop_fraction':box,'fields':{'patient_name':
                    'Read the exact handwritten patient name in this oriented crop. Exclude doctors, parents, signatures and printed labels. Return null if no handwritten patient name is visible.'},
                    'purpose':'HANDWRITTEN_PATIENT_NAME_ONLY','output':str(target.relative_to(output))})
    batch.write(output/'allowed_handwritten_name_jobs_v5.json',jobs)
    batch.write(output/'rotation_summary.json',{'pages_rotated':sum(len(d.get('rotations',[])) for d in first),
        'documents_rotated':sum(bool(d.get('rotations')) for d in first),'new_di_calls':0})
    print('New handwritten name crops',len(jobs),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('runs/uat_25_cases_v4_20261124'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--stage',choices=['prepare','bind','final'],required=True)
    args=parser.parse_args()
    if args.stage in {'prepare','bind'}:prepare(args.source,args.output,resume=args.stage=='bind')
    else:reconcile(args.output,prepare_handwriting=False)
