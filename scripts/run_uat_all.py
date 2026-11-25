"""Resumable all-case UAT extraction using local OCR and recorded provider stages."""
import argparse
import copy
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pymupdf
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from packages.layout_intelligence.engine import BundleDResult
from packages.ocr.tesseract_adapter import TesseractTextExtractor
from workers.unstructured_extraction.uat_evidence import di_lines, locate_value
from workers.unstructured_extraction.extraction_acceptance import ExtractionAcceptance
from workers.unstructured_extraction.local_completion import LocalLayoutCompletion
from workers.unstructured_extraction.observed_type import resolve_observed_type
from workers.unstructured_extraction.uat_policy import load_policy, nominate_type
from workers.unstructured_extraction.uat_cases import decide_case
from workers.unstructured_extraction.uat_recovery_rules import (
    case_name_candidates, confirm_mask_matches, masked_candidates, visual_evidence,
)
from workers.unstructured_extraction.uat_binding_v5 import bound_candidates, licence_content

SERVICE=LocalLayoutCompletion(profile_path=ROOT/'config/runtime_profiles/uat_evaluation_v1.yaml',
    labels_path=ROOT/'config/uat_layout_label_aliases.yaml')
ACCEPT=ExtractionAcceptance()
DESCRIPTIONS={
    'license_number':'Exact visible driving licence number; null if absent.',
    'license_expiry_date':'Expiry date explicitly labelled valid till or expiry; null if absent.',
    'tmt_interpretation':'Exact treadmill or exercise stress test conclusion; null if absent.',
    'patient_name':'Exact patient/card-holder name, excluding form labels, parent names and doctors. Null if absent.',
    'patient_dob':'Date of birth in DD/MM/YYYY. Do not substitute report/proposal dates; null if not visible.',
    'report_date':'Diagnostic report date in DD/MM/YYYY; null if absent.',
    'examination_date':'Date explicitly associated with the medical examination, DD/MM/YYYY; not an unrelated declaration date.',
    'identity_number':'Full visible PAN or Aadhaar identifier. Null if concealed or masked; never invent hidden digits.',
    'ecg_interpretation':'Exact ECG impression/interpretation text; null if not visible.',
    'content_kind':'Visible content category: portrait_photo, identity_card, medical_report, or other. Do not identify a person from their face.'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,indent=2),encoding='utf-8');temp.replace(path)


def inventory(archive,out):
    if (out/'inventory.json').exists():
        if (out/'summary.json').exists() and read(out/'summary.json').get('status')=='COMPLETE':
            raise ValueError('Completed runs are immutable; use scripts.replay_uat_contract with a new output directory')
        records=read(out/'inventory.json');policy=load_policy();changed=False
        for record in records:
            kind=nominate_type(record['document'],record['manifest_type'],policy)
            if kind==record['declared_type']: continue
            record['declared_type']=kind;changed=True
            path=Path(record['directory'])/'local.json'
            if path.exists():
                local=read(path)
                if local['stage']=='LOCAL':
                    layouts=[BundleDResult.model_validate_json(Path(p).read_text(encoding='utf-8')) for p in local['layouts']]
                    local.update(declared_type=kind,effective_type=kind,
                        decision=ACCEPT.decide(kind,layouts,expected_pages=record['pages'],
                            assets=local['assets'],candidates=local['candidates']))
                    write(path,local)
        if changed: write(out/'inventory.json',records)
        return records
    records=[];policy=load_policy()
    with zipfile.ZipFile(archive) as outer:
        for nested in sorted(n for n in outer.namelist() if n.endswith('/documents.zip')):
            case=nested.split('/')[-2]
            manifest=json.loads(outer.read(nested.replace('documents.zip','manifest.json')))
            types={entry['filename']:entry['document_type'] for entry in manifest}
            with zipfile.ZipFile(io.BytesIO(outer.read(nested))) as inner:
                files=[name for name in inner.namelist() if not name.endswith('/')]
                for index,name in enumerate(files,1):
                    payload=inner.read(name);suffix=Path(name).suffix.lower()
                    directory=out/'cases'/case/f'doc_{index:03d}'
                    directory.mkdir(parents=True,exist_ok=True)
                    source=directory/('source'+suffix);source.write_bytes(payload)
                    try:
                        if suffix=='.pdf':
                            with pymupdf.open(stream=payload,filetype='pdf') as pdf:
                                pages=len(pdf)
                        else:
                            with Image.open(io.BytesIO(payload)) as image:
                                pages=getattr(image,'n_frames',1)
                        error=None
                    except Exception as exc:  # noqa: BLE001 - inventory corrupt inputs explicitly
                        pages=0;error=type(exc).__name__
                    records.append({'id':f'{case}/doc_{index:03d}','case_id':case,'document':name,
                        'manifest_type':types.get(name,'OTHER'),
                        'declared_type':nominate_type(name,types.get(name,'OTHER'),policy),
                        'sha256':hashlib.sha256(payload).hexdigest(),'pages':pages,
                        'source':str(source.resolve()),'directory':str(directory.resolve()),'intake_error':error})
    write(out/'inventory.json',records)
    write(out/'batch_manifest.json',{'source_archive':str(archive.resolve()),
        'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
        'cases':len({r['case_id'] for r in records}),'documents':len(records),
        'pages':sum(r['pages'] for r in records),'manifest_types':dict(Counter(r['manifest_type'] for r in records)),
        'policy_sha256':hashlib.sha256((ROOT/'config/uat_extraction_acceptance.yaml').read_bytes()).hexdigest(),
        'no_reference_labels_used':True,'llm_provider':'azure_claude'})
    return records


def seed_records():
    seeds={};folder=ROOT/'runs/uat_10_azure_claude_fixed_20261124'
    for path in folder.glob('doc_*/FinalExtraction.json'):
        final=read(path);sha=final.get('sha256') or final.get('document_id')
        base=ROOT/'runs/uat_next_run'/path.parent.name
        seeds[sha]={'decision':final['extraction_acceptance'],
            'candidates':final['extracted_candidates'],'assets':[read(p)['asset'] for p in sorted(base.glob('page_*.json'))],
            'layouts':[str(p.resolve()) for p in sorted(base.glob('layout_*.json'))],
            'effective_type':final.get('document_type') or final['extraction_acceptance']['document_type'],
            'seed_from':str(path),'stage':'CACHED_CASCADE'}
    return seeds


def local_one(record,seeds):
    directory=Path(record['directory']);target=directory/'local.json'
    if target.exists():
        return read(target)
    started=time.perf_counter();pdf=None;source=None
    result=dict(record)
    try:
        if record['intake_error']:
            raise ValueError('INTAKE_'+record['intake_error'])
        if record['sha256'] in seeds:
            result.update(copy.deepcopy(seeds[record['sha256']]))
        else:
            assets=[];layouts=[];paths=[]
            if Path(record['source']).suffix.lower()=='.pdf':
                pdf=pymupdf.open(record['source'])
            else:
                source=Image.open(record['source'])
            for number in range(1,record['pages']+1):
                if pdf is not None:
                    pix=pdf[number-1].get_pixmap(dpi=200,alpha=False)
                    image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                else:
                    source.seek(number-1);image=source.convert('RGB')
                image.thumbnail((3500,3500))
                asset_path=directory/f'page_{number:03d}.png'
                image.save(asset_path,format='PNG')
                asset={'page':number,'path':str(asset_path.resolve()),'width':image.width,'height':image.height,
                    'sha256':hashlib.sha256(asset_path.read_bytes()).hexdigest()}
                lines=[] if record['declared_type'] in {'PERSON_PHOTO','GEOTAGPHOTO'} else TesseractTextExtractor(psm=11).extract(image)
                layout=SERVICE.extract_page(lines,page_number=number,width=image.width,height=image.height,engine='tesseract_psm_11',document_family=record['declared_type'])
                image.close()
                layout_path=directory/f'layout_{number:03d}.json'
                layout_path.write_text(layout.model_dump_json(indent=2),encoding='utf-8')
                write(directory/f'page_{number:03d}.json',{'asset':asset,'ocr_lines':[vars(line) for line in lines]})
                assets.append(asset);layouts.append(layout);paths.append(str(layout_path.resolve()))
            fields=SERVICE.complete(record['sha256'],layouts,document_family='UAT_'+record['declared_type'],type_verified=True)
            decision=ACCEPT.decide(record['declared_type'],layouts,expected_pages=record['pages'],
                assets=assets,candidates=fields['extracted_candidates'])
            result.update(assets=assets,layouts=paths,candidates=fields['extracted_candidates'],decision=decision,
                effective_type=record['declared_type'],stage='LOCAL')
    except Exception as exc:  # noqa: BLE001 - keep all cases represented in the denominator
        result.update(stage='TECHNICAL_FAILURE',error_type=type(exc).__name__,
            decision={'disposition':'TECHNICAL_FAILURE','extraction_stp_eligible':False,'reason_codes':[type(exc).__name__]})
    finally:
        if pdf is not None: pdf.close()
        if source is not None: source.close()
    result['local_seconds']=round(time.perf_counter()-started,3)
    write(target,result)
    return result


def evaluate(record,final=False):
    directory=Path(record['directory']);local=read(directory/'local.json')
    if local['stage'] in {'CACHED_CASCADE','TECHNICAL_FAILURE'} or (local['decision']['extraction_stp_eligible'] and not record.get('apply_recovery_v4')):
        write(directory/'final.json',local);return local
    layouts=[BundleDResult.model_validate_json(Path(path).read_text(encoding='utf-8')) for path in local['layouts']]
    sources=[];di_layouts=[];successful=[];pages=[]
    for number,(asset,layout) in enumerate(zip(local['assets'],layouts,strict=True),1):
        path=directory/f'di_page_{number:03d}.json';di=read(path) if path.exists() else {}
        lines=di_lines(di,asset['width'],asset['height']) if di.get('status')=='SUCCESS' else []
        sources.append((number,lines))
        if di.get('status')=='SUCCESS': successful.append(number)
        fresh=SERVICE.extract_page(lines,page_number=number,width=asset['width'],height=asset['height'],engine='azure_document_intelligence_read',document_family=record['declared_type']) if lines else layout
        pages.append(fresh)
        if lines: di_layouts.append(fresh)
    candidates=copy.deepcopy(local['candidates'])
    if di_layouts:
        fresh=SERVICE.complete(record['sha256'],di_layouts,document_family='UAT_'+record['declared_type'],type_verified=True)
        for name,items in fresh['extracted_candidates'].items(): candidates.setdefault(name,[]).extend(items)
    llm_records=[]
    if final:
        for path in sorted(directory.glob('llm_*.json')):
            llm=read(path);llm_records.append(llm)
            if llm['status']!='SUCCESS': continue
            page_number=next(i for i,a in enumerate(local['assets'],1) if a['path']==llm['source_image'])
            asset=local['assets'][page_number-1];box=llm['crop_fraction']
            region=(box[0]*asset['width'],box[1]*asset['height'],box[2]*asset['width'],box[3]*asset['height'])
            for field in llm['fields']:
                if field['insufficient_evidence'] or not field['value']: continue
                item=locate_value(field['value'],sources,page_number=page_number,region=region,mapping_provider='azure_claude',field_name=field['field_name'])
                if (not item and record.get('apply_recovery_v5') and field['field_name']=='patient_name'
                    and '_v5_handwritten_name_' in path.name):
                    from workers.unstructured_extraction.uat_recovery_rules import name_similarity
                    refs=[ref for ref in record.get('verified_name_sources',[]) if ref.get('source_verified')
                        and ref.get('document_id')!=record['id'] and ref.get('raw_confidence',0)>=.8
                        and name_similarity(field['value'],ref['value'])>=.90]
                    if refs:
                        from workers.unstructured_extraction.uat_recovery_rules import name_key
                        exact=any(re.sub(r'[^a-z]','',name_key(field['value']))==re.sub(r'[^a-z]','',name_key(ref['value'])) for ref in refs)
                        item={'value':field['value'],'raw_confidence':0.0,'ocr_confidence_available':False,
                            'confidence_note':'No matching OCR witness; zero is a conservative routing score, not measured OCR confidence.',
                            'model_confidence':field.get('confidence'),'engine':'azure_claude_handwritten_name_crop',
                            'field_association':'HANDWRITTEN_CROP_CASE_NAME_MATCH','page_number':page_number,
                            'bounding_box':dict(zip(['x0','y0','x1','y1'],region,strict=True)),
                            'evidence_reference':str(path.resolve()),'source_image':asset['path'],
                            'crop_fraction':box,'independent_document_refs':[ref['document_id'] for ref in refs]}
                        item['source_reading_ambiguous']=not exact
                if item:
                    item['mapping_record']=str(path.resolve())
                    candidates.setdefault(field['field_name'],[]).append(item)
    visual={}
    known_names=record.get('case_known_names',[])
    if record.get('apply_recovery_v4'):
        kind=record['declared_type']
        if kind in {'AADHAAR','PAN','DRIVING_LICENSE','ECG','TMT'} or not any(page.lines for page in pages):
            visual_path=directory/'visual_evidence.json'
            visual=read(visual_path) if visual_path.exists() else {}
            if visual.get('version')!='local-visual-v4-2': visual=visual_evidence(local['assets'],pages)
            write(visual_path,visual)
        if kind in {'AADHAAR','IDENTITY_PROOF'}:
            masked=record.get('masked_candidates')
            if masked is None: masked=masked_candidates(local['assets'],pages)
            candidates['identity_number_masked']=confirm_mask_matches(copy.deepcopy(masked),record.get('case_aadhaar_suffixes',[]))
        if kind in {'PATH','MER','ECG','TMT'} and known_names:
            candidates.setdefault('patient_name',[]).extend(case_name_candidates(pages,known_names))
    no_text=not any((token.confidence or 0)>=.80 and re.search(r'\w{3}',token.text)
        for page in [*layouts,*pages] for line in page.lines for token in line.tokens)
    routing_sources=[(number,[line for line in lines if (line.confidence or 0)>=.80 and re.search(r'\w{3}',line.text)])
        for number,lines in sources] if no_text else sources
    resolution=resolve_observed_type(record['declared_type'],records=llm_records,assets=local['assets'],
        sources=routing_sources,candidates=candidates,policy=ACCEPT.config,successful_di_pages=successful,
        local_portraits=visual.get('portraits') if no_text else None)
    binding_audit=[]
    if record.get('apply_recovery_v5'):
        if record['declared_type'] in {'PAN','AADHAAR','IDENTITY_PROOF','DRIVING_LICENSE','OTHER'} and licence_content(pages):
            resolution.update(effective_type='DRIVING_LICENSE',changed=True,
                reason_codes=['SOURCE_LICENCE_CARD_HEADING_AND_FIELDS'],licence_card_supplied=True)
        candidates,binding_audit=bound_candidates(resolution['effective_type'],pages,candidates)
    if record.get('apply_recovery_v6'):
        from workers.unstructured_extraction.uat_binding_v6 import recover
        recovered_path=directory/'local_field_recovery_v6.json'
        if recovered_path.exists():
            for field,items in read(recovered_path).get('candidates',{}).items():
                candidates.setdefault(field,[]).extend(copy.deepcopy(items))
        candidates=recover(resolution['effective_type'],pages,candidates)
    decision=ACCEPT.decide(resolution['effective_type'],pages,expected_pages=record['pages'],assets=local['assets'],candidates=candidates,
        filename=record['document'],visual=visual,known_names=known_names,
        case_verification_required=bool(record.get('apply_recovery_v4')),
        verified_name_sources=record.get('verified_name_sources',[]),document_id=record['id'])
    stage=('LOCAL_DI_CLAUDE' if llm_records else 'LOCAL_DI' if successful
        else 'LOCAL_UNSUPPORTED_SCHEMA' if record['declared_type']=='OTHER' else 'LOCAL')
    result=dict(local,candidates=candidates,decision=decision,effective_type=resolution['effective_type'],
        type_resolution=resolution,stage=stage,llm_records=llm_records,visual_evidence=visual,binding_audit=binding_audit)
    write(directory/'final.json',result)
    return result


def prepare_jobs(records,out,stage):
    jobs=[]
    already_queued=set()
    if stage=='llm':
        for path in out.glob('llm_jobs_*_[012].json'):
            already_queued.update(item['output'] for item in read(path) if 'output' in item)
    for record in records:
        directory=Path(record['directory'])
        if not (directory/'local.json').exists(): continue
        local=read(directory/'local.json')
        if local['stage'] in {'CACHED_CASCADE','TECHNICAL_FAILURE'} or local['decision']['extraction_stp_eligible']: continue
        kind=record['declared_type']
        if kind=='OTHER': continue  # no invented acceptance rules for unsupported schemas
        if stage=='llm' and any(not (directory/f"di_page_{asset['page']:03d}.json").exists()
            or read(directory/f"di_page_{asset['page']:03d}.json").get('status')=='RESERVED'
            for asset in local['assets']):
            continue
        current=evaluate(record,final=False) if stage=='llm' else local
        if current['decision']['extraction_stp_eligible']: continue
        if stage=='di':
            for asset in local['assets']:
                number=asset['page']
                completed=directory/f'di_page_{number:03d}.json'
                if completed.exists(): continue
                jobs.append({'id':f"{record['id']}/page_{number:03d}",'image':asset['path'],
                    'output':str((directory/f'di_page_{number:03d}.json').relative_to(out))})
        else:
            reasons=current['decision']['reason_codes']
            gaps={r.split(':',1)[1] for r in reasons if ':' in r}
            fields={name:DESCRIPTIONS[name] for name in ACCEPT.config['profiles'][kind]['required_fields'] if name in gaps}
            if kind in {'AADHAAR','PAN'}: fields['content_kind']=DESCRIPTIONS['content_kind']
            if not fields: continue
            for asset in local['assets']:
                number=asset['page'];parts=[]
                if kind=='MER':
                    if number==1:
                        header={k:v for k,v in fields.items() if k!='examination_date'}
                        if header: parts.append(('header',(.02,.06,.98,.40),header))
                    if number==record['pages'] and 'examination_date' in fields:
                        parts.append(('examiner',(.02,.60,.98,.98),{'examination_date':fields['examination_date']}))
                elif kind in {'AADHAAR','PAN','IDENTITY_PROOF','DRIVING_LICENSE'}:
                    parts.append(('identity',(.02,.02,.98,.98),fields))
                else:
                    interpretation='tmt_interpretation' if kind=='TMT' else 'ecg_interpretation'
                    parts.append(('header',(.02,.02,.98,.50),{k:v for k,v in fields.items() if k!=interpretation}))
                    if interpretation in fields:
                        parts.append(('interpretation',(.02,.35,.98,.95),{interpretation:fields[interpretation]}))
                for label,box,requested in parts:
                    output=str((directory/f'llm_p{number:03d}_{label}.json').relative_to(out))
                    if requested and output not in already_queued and not (directory/f'llm_p{number:03d}_{label}.json').exists():
                        jobs.append({'id':f"{record['id']}/p{number}_{label}",'image':asset['path'],
                            'crop_fraction':box,'fields':requested,
                            'output':output})
    batch=time.strftime('%H%M%S')
    write(out/(stage+'_jobs.json'),jobs)
    for shard in range(3): write(out/f'{stage}_jobs_{batch}_{shard}.json',jobs[shard::3])
    write(out/f'{stage}_latest_queue.json',{'jobs':len(jobs),'shards':[str((out/f'{stage}_jobs_{batch}_{i}.json').resolve()) for i in range(3)]})
    print(stage,'jobs',len(jobs),flush=True)


def report(records,out,final=False):
    rows=[];cases=defaultdict(list);case_documents=defaultdict(list);reasons=Counter()
    for record in records:
        path=Path(record['directory'])/('final.json' if final else 'local.json')
        if not path.exists(): continue
        item=read(path);decision=item['decision']
        row={'case_id':record['case_id'],'document':record['document'],'manifest_type':record['manifest_type'],
            'declared_type':record['declared_type'],'effective_type':item.get('effective_type',record['declared_type']),
            'pages':record['pages'],'outcome':decision['disposition'],'reason':';'.join(decision['reason_codes']),
            'stage':item['stage'],'evidence_file':str(path.resolve())}
        rows.append(row);cases[row['case_id']].append(row)
        case_documents[record['case_id']].append(item)
        reasons.update(decision['reason_codes'])
    if rows:
        with (out/'scorecard.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    case_rows=[{'case_id':case,'documents':len(values),'completed':sum(v['outcome']=='EXTRACTION_COMPLETED' for v in values),
        'case_complete':len(values)==sum(r['case_id']==case for r in records) and decide_case(case_documents[case])['case_complete']} for case,values in cases.items()]
    if case_rows:
        with (out/'case_scorecard.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(case_rows[0]));writer.writeheader();writer.writerows(case_rows)
    completed=sum(row['outcome']=='EXTRACTION_COMPLETED' for row in rows)
    summary={'status':'COMPLETE' if final and len(rows)==len(records) else 'IN_PROGRESS',
        'requested_cases':len({r['case_id'] for r in records}),'requested_documents':len(records),
        'processed_documents':len(rows),'pending_documents':len(records)-len(rows),'pages':sum(r['pages'] for r in records),
        'completed_documents':completed,'extraction_stp_rate':completed/len(records),
        'fully_completed_cases':sum(row['case_complete'] for row in case_rows),
        'case_stp_rate':sum(row['case_complete'] for row in case_rows)/len({r['case_id'] for r in records}),
        'outcomes':dict(Counter(row['outcome'] for row in rows)),'review_reasons':dict(reasons),
        'scope':'Extraction completeness under configured document schemas. Photo assets counted separately by type; correctness and underwriting unmeasured.',
        'unsupported_manifest_types':dict(Counter(row['manifest_type'] for row in rows if row['declared_type']=='OTHER')),
        'correct_stp_rate':None}
    summary['asset_only_completions']=sum(row['outcome']=='EXTRACTION_COMPLETED' and
        ACCEPT.config['profiles'].get(row['effective_type'],{}).get('asset_only',False) for row in rows)
    summary['structured_document_completions']=completed-summary['asset_only_completions']
    if final and (out/'provider_summary.json').exists():
        summary['provider_jobs']=read(out/'provider_summary.json')
    write(out/'summary.json',summary)
    return summary


def verify_cloud_outputs(out):
    if not (out/'di_jobs.json').exists() or not (out/'llm_jobs.json').exists():
        raise RuntimeError('Prepare the DI and LLM job plans before final reconciliation')
    plans={'di':read(out/'di_jobs.json'),'claude':[]}
    for path in out.glob('llm_jobs_*_[012].json'): plans['claude'].extend(read(path))
    summary={}
    for stage,jobs in plans.items():
        unique={job['output']:job for job in jobs};results=[]
        for name in unique:
            path=out/name
            if not path.exists() or read(path).get('status') not in {'SUCCESS','FAILED'}:
                raise RuntimeError(f'Provider jobs still pending for {stage}; final status withheld')
            results.append(read(path))
        summary[stage]={'planned':len(unique),'statuses':dict(Counter(r['status'] for r in results))}
        if stage=='claude':
            summary[stage]['reported_tokens']={key:sum(r.get('usage',{}).get(key,0) for r in results)
                for key in ['input_tokens','output_tokens','total_tokens']}
            summary[stage]['provider_names']=dict(Counter(r.get('provider','unknown') for r in results))
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=Path.home()/'Downloads'/'UAT Latest.zip')
    parser.add_argument('--out-dir',type=Path,default=ROOT/'runs/uat_all_cases_20261124')
    parser.add_argument('--stage',choices=['inventory','local','di-jobs','llm-jobs','final'],required=True)
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args();out=args.out_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ['OMP_THREAD_LIMIT']='1'
    records=inventory(args.archive,out)
    if args.stage=='inventory': print(json.dumps(read(out/'batch_manifest.json'),indent=2));return
    if args.stage=='local':
        seeds=seed_records()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures={pool.submit(local_one,record,seeds):record for record in records}
            for number,future in enumerate(as_completed(futures),1):
                item=future.result()
                print('LOCAL',number,len(records),item['id'],item['decision']['disposition'],flush=True)
                if number%10==0: report(records,out)
        print(json.dumps(report(records,out),indent=2))
    elif args.stage in {'di-jobs','llm-jobs'}:
        prepare_jobs(records,out,'di' if args.stage=='di-jobs' else 'llm')
    else:
        write(out/'provider_summary.json',verify_cloud_outputs(out))
        for index,record in enumerate(records,1):
            evaluate(record,final=True)
            if index%25==0: print('FINAL',index,len(records),flush=True)
        print(json.dumps(report(records,out,final=True),indent=2))


if __name__=='__main__': main()
