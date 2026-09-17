"""Validate source-bound visual annotations and export their review artifacts."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from zipfile import ZipFile
from PIL import Image


def export_labels(archive_path, output):
    archive_path, output = Path(archive_path), Path(output)
    records = [json.loads(line) for line in (output/'ai_visual_labels.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    keys = [(r['document'],r['page_number']) for r in records]
    if len(keys)!=len(set(keys)):
        raise ValueError('Duplicate document/page annotation')
    by_key = dict(zip(keys,records,strict=True))
    manifest=[]; flat=[]
    with ZipFile(archive_path) as archive:
        documents=sorted(n for n in archive.namelist() if not n.endswith('/'))
        for name in documents:
            data=archive.read(name)
            digest=hashlib.sha256(data).hexdigest()
            with Image.open(io.BytesIO(data)) as image:
                pages=image.n_frames
                for page in range(1,pages+1):
                    record=by_key.get((name,page))
                    if record and record['source_sha256']!=digest:
                        raise ValueError(f'Source hash mismatch: {name}')
                    manifest.append({'document':name,'page_number':page,'source_sha256':digest,
                                     'annotation_status':record['annotation_status'] if record else 'UNLABELED'})
    if set(by_key)-{(m['document'],m['page_number']) for m in manifest}:
        raise ValueError('Annotation does not match archive document/page')
    def add(record,field_name,value,row=None):
        status=value['status']
        if status not in {'TRANSCRIBED','BLANK','AMBIGUOUS','UNREADABLE','NOT_APPLICABLE'}:
            raise ValueError(f'Unknown label status: {status}')
        if status=='BLANK' and value['raw_value']!='':
            raise ValueError('Blank label contains text')
        flat.append({'document':record['document'],'page_number':record['page_number'],
                     'source_sha256':record['source_sha256'],'field_name':field_name,
                     'service_row':row or '', 'source_form_box':value['source_form_box'],
                     'raw_value':value['raw_value'],
                     'normalized_value':json.dumps(value.get('normalized_value'),ensure_ascii=True),
                     'label_status':status,'annotation_method':record['annotation_method'],
                     'human_verified':'false','reviewer':'','note':value.get('note','')})
    for record in records:
        for name,value in record['fields'].items():add(record,name,value)
        rows=[row['row_number'] for row in record['service_lines']]
        if len(rows)!=len(set(rows)) or set(rows)&set(record['empty_service_line_rows']):
            raise ValueError('Conflicting service row annotation')
        for row in record['service_lines']:
            for name,value in row['fields'].items():add(record,name,value,row['row_number'])
    (output/'page_manifest.jsonl').write_text(''.join(json.dumps(m)+'\n' for m in manifest),encoding='utf-8')
    with (output/'ai_visual_labels.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(flat[0]))
        writer.writeheader();writer.writerows(flat)
    with archive_path.open('rb') as source_stream:
        archive_digest=hashlib.file_digest(source_stream,'sha256').hexdigest()
    summary={'created_at':datetime.now(timezone.utc).isoformat(),'archive':str(archive_path),
             'archive_sha256':archive_digest,
             'requested_scope':'All extracted fields and service lines, all documents/pages',
             'documents_total':len(documents),'pages_total':len(manifest),
             'documents_with_ai_draft':len({r['document'] for r in records}),
             'pages_with_ai_draft':len(records),'pages_unlabeled':len(manifest)-len(records),
             'header_labels':sum(len(r['fields']) for r in records),
             'service_lines':sum(len(r['service_lines']) for r in records),
             'service_cell_labels':sum(len(row['fields']) for r in records for row in r['service_lines']),
             'label_status_counts':dict(Counter(r['label_status'] for r in flat)),
             'human_verified_pages':0,'status':'PARTIAL_AI_DRAFT',
             'predictions_used':False,'ground_truth_certified':False,
             'notes':['Direct source-image transcriptions by the assistant; subject to visual transcription errors.',
                      'The initial batch is the first ten sorted documents, not a representative accuracy sample.',
                      'Unlabeled pages are not treated as blank or correct.',
                      'Ambiguous cells must be excluded from scoring until resolved.',
                      'No labeling background process is running; the OCR evaluation is a separate process.']}
    (output/'labeling_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    html=['<!doctype html><meta charset="utf-8"><title>Source-image annotation review</title>',
          '<style>body{font-family:system-ui;margin:24px;color:#172033}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd3dc;padding:7px;text-align:left;white-space:pre-wrap}summary{padding:14px;background:#eef2f7;cursor:pointer}img{max-width:100%}.layout{display:grid;grid-template-columns:1fr 1fr;gap:20px}.source{position:sticky;top:0;align-self:start;max-height:95vh;overflow:auto}h1{margin-bottom:8px}@media(max-width:900px){.layout{display:block}}</style>',
          '<h1>AI draft source-image labels</h1>',
          f'<p>{len(records)} / {len(manifest)} pages annotated. These are draft transcriptions, not human-verified ground truth.</p>',
          '<p>Blank means the source cell is empty. Ambiguous means unresolved. No OCR predictions are displayed.</p>']
    for record in records:
        html.append('<details><summary>'+escape(record['document'])+' — page '+str(record['page_number'])+'</summary><div class="layout"><div class="source"><a href="'+escape(record['view'],quote=True)+'"><img src="'+escape(record['view'],quote=True)+'"></a></div><div>')
        for title,values in [('Header fields',record['fields'])]+[(f"Service row {row['row_number']}",row['fields']) for row in record['service_lines']]:
            html.append('<h2>'+escape(title)+'</h2><table><tr><th>Field / box</th><th>Transcription</th><th>Status / note</th></tr>')
            for name,value in values.items():
                html.append('<tr><td>'+escape(name+' / '+value['source_form_box'])+'</td><td>'+escape(value['raw_value'])+'</td><td>'+escape(value['status']+' '+value.get('note',''))+'</td></tr>')
            html.append('</table>')
        html.append('<p>Empty service rows: '+escape(str(record['empty_service_line_rows']))+'</p></div></div></details>')
    (output/'review.html').write_text('\n'.join(html),encoding='utf-8')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(export_labels(args.archive,args.output),indent=2))
