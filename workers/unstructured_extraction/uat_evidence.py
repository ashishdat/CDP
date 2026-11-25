"""Bounded OCR witnesses for model suggestions; model confidence is not OCR evidence."""
import re

from packages.ocr.text_extraction import TextLine
from workers.unstructured_extraction.uat_values import DATE_FIELDS, DATE_PATTERN, date_value


def di_lines(record,width,height):
    pages=(record.get('payload',{}).get('analyzeResult') or {}).get('pages',[])
    if not pages: return []
    page=pages[0];sx=width/page['width'];sy=height/page['height']
    return [TextLine(word['content'],min(word['polygon'][0::2])*sx,min(word['polygon'][1::2])*sy,
        max(word['polygon'][0::2])*sx,max(word['polygon'][1::2])*sy,word.get('confidence',0))
        for word in page.get('words',[]) if word.get('polygon')]


def compact(value):
    return re.sub(r'[^a-z0-9]','',value.casefold())


def date_role(prefix):
    patterns={'patient_dob':r'date\s*of\s*birth|birth\s*date|\bdob\b',
        'report_date':r'report(?:ed)?\s*(?:date|on)|date\s*of\s*(?:report|test)|test\s*date',
        'collection_date':r'collect(?:ion|ed)\s*(?:date|on)',
        'registration_date':r'(?:registered|registration)\s*(?:date|on|time)?',
        'received_date':r'receiv(?:ed|ing)\s*(?:date|on|time)',
        'print_date':r'print(?:ed)?\s*(?:date|on)',
        'examination_date':r'examination\s*date|date\s*of\s*(?:medical\s*)?examination',
        'license_expiry_date':r'valid\s*(?:till|until)|expir[ey]\s*date|date\s*of\s*expiry',
        'declaration_date':r'declaration\s*date|signature\s*date'}
    found=[(match.end(),kind) for kind,pattern in patterns.items()
        for match in re.finditer(pattern,prefix,re.IGNORECASE)]
    return max(found)[1] if found else None


def locate_value(value,sources,*,page_number=None,region=None,mapping_provider='azure_openai',field_name=None):
    needle=compact(value)
    if not needle: return None
    for page,lines in sources:
        if page_number is not None and page!=page_number: continue
        if region is not None:
            x0,y0,x1,y1=region
            lines=[line for line in lines if x0<=(line.x0+line.x1)/2<=x1 and y0<=(line.y0+line.y1)/2<=y1]
        text='';offsets=[]
        for line in lines:
            fragment=compact(line.text)
            offsets.append((len(text),len(text)+len(fragment),line));text+=fragment
        start=text.find(needle);raw=value
        if start>=0:
            tokens=[line for left,right,line in offsets if left<start+len(needle) and right>start]
        elif field_name in DATE_FIELDS:
            joined='';spans=[]
            for line in lines:
                spans.append((len(joined),len(joined)+len(line.text),line));joined+=line.text+' '
            target=date_value(value);tokens=[]
            for match in re.finditer(DATE_PATTERN,joined):
                source=date_value(match.group())
                same=source['canonical_value'] and source['canonical_value']==target['canonical_value']
                # A model's century expansion is not source evidence. Preserve
                # only the visible short-year string and keep it ambiguous.
                short=source['year_ambiguous'] and target['canonical_value'] and re.sub(r'\D','',match.group())==re.sub(r'\D','',value)[:-4]+re.sub(r'\D','',value)[-2:]
                if same or short:
                    raw=match.group();tokens=[line for left,right,line in spans if left<match.end() and right>match.start()]
                    break
        else: tokens=[]
        if not tokens: continue
        first=lines.index(tokens[0]);height=max(1,tokens[0].y1-tokens[0].y0)
        prefix=' '.join(line.text for line in lines[max(0,first-12):first]
            if abs(line.y0-tokens[0].y0)<=2*height)
        role=date_role(prefix) if field_name in DATE_FIELDS else None
        return {'value':raw,'model_value':value,'engine':f'azure_document_intelligence_read+{mapping_provider}_mapping',
            'raw_confidence':min(line.confidence or 0 for line in tokens),
            'evidence_reference':f'di:page:{page}:llm_value_located_in_ocr',
            'field_association':'LLM_VALUE_LOCATED_IN_OCR','page_number':page,
            'date_role':role,'role_conflict':bool(role and role!=field_name),
            'bounding_box':{'x0':min(t.x0 for t in tokens),'y0':min(t.y0 for t in tokens),
                'x1':max(t.x1 for t in tokens),'y1':max(t.y1 for t in tokens)}}
    return None
