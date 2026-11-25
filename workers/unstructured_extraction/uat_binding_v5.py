"""Position/label binding for identity names, medical names and report dates."""
import copy
import re

from workers.unstructured_extraction.uat_evidence import date_role
from workers.unstructured_extraction.uat_recovery_rules import name_key, name_similarity
from workers.unstructured_extraction.uat_validation import valid_scalar
from workers.unstructured_extraction.uat_values import (
    DATE_FIELDS,
    DATE_PATTERN,
    date_value,
    identity_value,
)

MEDICAL={'PATH','MER','ECG','TMT'}
NAME_STOP=r'\b(?:received(?: date)?|registered(?: on)?|collected(?: on| date)?|collection(?: time| date)?|report(?:ed)?(?: on| date| time)?|receiving time|transaction id|patient id|bill\s*(?:no|number)|MR\s*(?:no|number)|reg(?:istration)?\s*(?:no|number)|lab\s*id|referral|ref(?:erred)?\.? by|doctor name|cardiac electric|age|sex|gender|HR)\b'


def source_rows(page):
    tokens=[token for line in page.lines for token in line.tokens]
    rows=[]
    for token in sorted(tokens,key=lambda t:(t.bbox.y0,t.bbox.x0)):
        cy=(token.bbox.y0+token.bbox.y1)/2
        row=next((row for row in reversed(rows[-5:]) if abs(row['cy']-cy)<=.55*max(1,token.bbox.y1-token.bbox.y0)),None)
        if row is None:
            row={'cy':cy,'tokens':[]};rows.append(row)
        row['tokens'].append(token)
    for row in rows:
        row['tokens'].sort(key=lambda t:t.bbox.x0)
        row['text']=' '.join(t.text for t in row['tokens'])
    return rows


def witness(value,row,binding,*,start=0,end=None):
    text=row['text'];pos=text.casefold().find(value.casefold(),start,end)
    if pos<0:return None
    spans=[];offset=0
    for token in row['tokens']:
        left=offset;offset+=len(token.text)+1
        if left<pos+len(value) and offset-1>pos:spans.append(token)
    if not spans:return None
    page=spans[0].page_number
    return {'value':value,'raw_confidence':min(t.confidence or 0 for t in spans),
        'page_number':page,'field_association':binding,
        'evidence_reference':f'page:{page}:{binding}:{int(spans[0].bbox.x0)}:{int(spans[0].bbox.y0)}',
        'bounding_box':{'x0':min(t.bbox.x0 for t in spans),'y0':min(t.bbox.y0 for t in spans),
                        'x1':max(t.bbox.x1 for t in spans),'y1':max(t.bbox.y1 for t in spans)}}


def pan_holder(pages):
    """PAN holders precede father/DOB; explicit holder labels take priority.

    Do not use proximity to a date as proof that the closest name is the holder:
    on older cards that closest row is normally the father's name.
    """
    found=[];evidence=[]
    for page in pages:
        rows=source_rows(page);text=' '.join(r['text'] for r in rows)
        if not re.search(r'income\s*tax|permanent\s*account',text,re.IGNORECASE):continue
        dob_rows=[i for i,row in enumerate(rows) if re.search(DATE_PATTERN,row['text'])]
        if not dob_rows:continue
        before=rows[:dob_rows[0]]
        issuer_bottom=max((row['cy'] for row in before if re.search(r'income\s*tax|govt|government|permanent\s*account',row['text'],re.IGNORECASE)),default=-1)
        explicit=[];unlabelled=[]
        for row in before:
            text=row['text']
            if row['cy']<=issuer_bottom:continue
            if re.search(r'father|mother|parent|signature|income|government|govt|department|account|india|card|tax|satyamev',text,re.IGNORECASE):continue
            match=re.search(r'^\s*(?:name|holder(?:\s+name)?)\s*[:：]?\s+(.+)',text,re.IGNORECASE)
            value=match.group(1).strip() if match else text.strip()
            if valid_scalar('patient_name',value) and len(re.sub(r'[^A-Za-z]','',value))>=3 and all((t.confidence or 0)>=.60 for t in row['tokens']):
                item=witness(value,row,'PAN_HOLDER_POSITION_AND_LABEL')
                if item:
                    (explicit if match else unlabelled).append(item)
        eligible=explicit or unlabelled
        if eligible:
            # The first Latin name row below issuer headings is the holder;
            # the later Latin name before DOB is retained as parent evidence.
            found.append({**eligible[0],'holder_binding':'EXPLICIT_NAME_LABEL' if explicit else 'FIRST_NAME_ABOVE_PARENT_AND_DOB'})
            evidence.append({'holder':eligible[0],'other_name_rows':eligible[1:],
                             'basis':'PAN_ISSUER_HEADING_NAME_ORDER_AND_DOB'})
    return found,evidence


def licence_content(pages):
    text=' '.join(line.text for page in pages for line in page.lines)
    if re.search(r'medical\s*exam|form\s*of\s*identification|employment\s*identity|questions.+medical examiner',text,re.IGNORECASE):
        return False
    return bool(re.search(r'driving\s+licen[cs]e',text,re.IGNORECASE)
                and re.search(r'valid(?:ity| till)',text,re.IGNORECASE)
                and re.search(r'licen[cs]e\s*(?:no|number)|issued\s*by|indian\s*union',text,re.IGNORECASE))


def licence_date_role(item,rows):
    box=item['bounding_box'];cx=(box['x0']+box['x1'])/2;cy=(box['y0']+box['y1'])/2
    if box['y1']-box['y0']>box['x1']-box['x0']:
        return None  # Vertical side print is the issue annotation, not DOB/expiry.
    height=max(1,box['y1']-box['y0']);choices=[]
    patterns={'patient_dob':r'date\s*of\s*birth|\bDOB\b',
              'license_expiry_date':r'validity\s*\(\s*NT\s*\)|valid\s*till\s*\(\s*NT\s*\)|valid\s*till(?!\s*\(\s*TR)|expir[ey]\s*date'}
    for row in rows:
        for role,pattern in patterns.items():
            for match in re.finditer(pattern,row['text'],re.IGNORECASE):
                label=witness(match.group(),row,'LICENCE_LABEL_POSITION')
                if not label:continue
                lb=label['bounding_box'];lx=(lb['x0']+lb['x1'])/2;ly=(lb['y0']+lb['y1'])/2
                dy=cy-ly;dx=abs(cx-lx)
                same_row=abs(dy)<=height and box['x0']>=lb['x1']-height and box['x0']-lb['x1']<=5*height
                below=0<dy<=5*height and dx<=max(lb['x1']-lb['x0'],box['x1']-box['x0'])*.75
                if same_row or below:choices.append((0 if same_row else 1,abs(dy)+dx,role))
    return min(choices)[2] if choices else None


def bound_candidates(kind,pages,candidates):
    result=copy.deepcopy(candidates);audit=[]
    # Preserve rejected spans, but exclude demonstrated label contamination.
    for item in list(result.get('patient_name',[])):
        value=item.get('value','');clean=re.split(NAME_STOP,value,flags=re.IGNORECASE)[0].strip(' :')
        clean=re.sub(r'^(?:file\s+assured|full\s+name\s+of\s+(?:the\s+)?life\s+assured|\(LA\))\s*[:：]?\s*','',clean,flags=re.IGNORECASE)
        if clean!=value:
            item.update(role_conflict=True,rejection_basis='NAME_LABEL_BOUNDARY',untrimmed_value=value)
            if valid_scalar('patient_name',clean):
                for page in pages:
                    for row in source_rows(page):
                        recovered=witness(clean,row,'SCHEMA_LABEL_BOUNDARY')
                        if recovered:result['patient_name'].append(recovered);break
                    else:continue
                    break
    holders,pan_evidence=pan_holder(pages) if kind in {'PAN','IDENTITY_PROOF'} else ([],[])
    if holders:
        for item in result.get('patient_name',[]):
            if not any(name_similarity(item['value'],holder['value'])>=.90 for holder in holders):
                item.update(role_conflict=True,rejection_basis='PAN_PARENT_OR_NON_HOLDER_POSITION')
        result.setdefault('patient_name',[]).extend(holders);audit.extend(pan_evidence)
    elif kind in {'PAN','IDENTITY_PROOF'} and any(identity_value(item.get('value',''))['kind']=='full_pan'
                                                for item in result.get('identity_number',[])):
        for item in result.get('patient_name',[]):
            item.update(role_conflict=True,rejection_basis='PAN_HOLDER_BINDING_UNCONFIRMED')
    for page in pages:
        rows=source_rows(page);page_text=' '.join(row['text'] for row in rows)
        certificate=kind=='MER' and bool(re.search(r'certificate|signature\s*of\s*doctor|name\s*of\s*doctor',page_text,re.IGNORECASE))
        for i,row in enumerate(rows):
            text=row['text']
            if kind in MEDICAL:
                # Names attached to explicit labels, including a cover sheet.
                m=re.search(r'(?:patient\s*name|full\s*name\s*of\s*(?:the\s*)?life\s*assured|life\s*to\s*be\s*assured\s*(?:\(LA\)|:)|\bname\s*:)\s*[:：]?\s*(.+)',text,re.IGNORECASE)
                if m:
                    value=re.split(NAME_STOP,m.group(1),flags=re.IGNORECASE)[0].strip(' :')
                    if valid_scalar('patient_name',value):
                        item=witness(value,row,'SCHEMA_LABEL_BOUNDARY')
                        if item:result.setdefault('patient_name',[]).append(item)
            for match in re.finditer(DATE_PATTERN,text):
                prefix=text[:match.start()];field=None
                if kind=='MER' and certificate and re.search(r'\bdate\s*[:：]?\s*$',prefix,re.IGNORECASE):
                    field='examination_date';binding='CERTIFICATE_DATE_POSITION'
                elif kind in {'ECG','TMT','PATH'} and re.search(r'(?:report(?:ed|ing)?\s*(?:date|on|time)|recorded|test\s*date|\bdate)\s*[:：]?\s*$',prefix,re.IGNORECASE):
                    if not re.search(r'collect|registr|receiv|birth|download|issue',prefix,re.IGNORECASE):
                        field='report_date';binding='DOCUMENT_DATE_POSITION'
                elif kind=='DRIVING_LICENSE' and re.search(r'date\s*of\s*birth|\bDOB',prefix,re.IGNORECASE):
                    field='patient_dob';binding='LICENCE_LABEL_POSITION'
                if kind=='DRIVING_LICENSE':
                    item=witness(match.group(),row,'LICENCE_LABEL_POSITION')
                    field=licence_date_role(item,rows) if item else None
                    binding='LICENCE_LABEL_POSITION'
                if field:
                    item=witness(match.group(),row,binding)
                    if item:result.setdefault(field,[]).append(item)
            if kind=='DRIVING_LICENSE':
                match=re.search(r'\b([A-Z]{2}\s*\d{2}\s*\d{4}\s*\d{7})\b',text)
                if match:
                    item=witness(match.group(),row,'LICENCE_LABEL_POSITION')
                    if item:result.setdefault('license_number',[]).append(item)
                # Newer smart cards put an unlabelled number and then DOB/validity.
                match=re.search(r'\bName\s*[:：]?\s+(.+?)(?=\s+(?:date|birth|blood|son|daughter|wife)\b|$)',text,re.IGNORECASE)
                if match and not re.search(r'father|mother|son/daughter',text,re.IGNORECASE):
                    value=match.group(1).strip()
                    if valid_scalar('patient_name',value):
                        item=witness(value,row,'LICENCE_LABEL_POSITION')
                        if item:result.setdefault('patient_name',[]).append(item)
            # DOB values on PAN cards can be standalone, anchored by issuer/layout.
            if holders and re.fullmatch(r'\s*'+DATE_PATTERN+r'\s*',text):
                item=witness(text.strip(),row,'PAN_HOLDER_POSITION_AND_LABEL')
                if item:result.setdefault('patient_dob',[]).append(item)
    # Names on a doctor/parent/referrer row cannot inherit a patient-name label
    # from a neighbouring row or column. Match the candidate's actual location.
    for item in result.get('patient_name',[]):
        matches=[]
        for page in pages:
            for row in source_rows(page):
                source=witness(item.get('value',''),row,'NAME_ROLE_WITNESS')
                if not source or source['page_number']!=item.get('page_number'):continue
                start=row['text'].casefold().find(item['value'].casefold());prefix=row['text'][:start]
                roles=[]
                for role,pattern in {'patient':r'patient\s*name|full\s*name\s*of\s*(?:the\s*)?life\s*assured|^\s*name\s*:',
                    'doctor':r'doctor\s*name|name\s*of\s*doctor|consultant\s*name',
                    'parent':r"father(?:'s)?\s*name|mother(?:'s)?\s*name|(?:S|D|C|W)\s*/\s*O\s*[:：]?",
                    'referrer':r'referred\s*by|referral|ref\.?\s*by'}.items():
                    roles.extend((m.end(),len(m.group()),role) for m in re.finditer(pattern,prefix,re.IGNORECASE))
                if not roles:continue
                role=max(roles)[2];box=item.get('bounding_box',{});sb=source['bounding_box']
                distance=abs(box.get('x0',sb['x0'])-sb['x0'])+abs(box.get('y0',sb['y0'])-sb['y0'])
                matches.append((distance,role))
        if matches:
            role=min(matches,key=lambda pair:pair[0])[1]
            if role!='patient':item.update(role_conflict=True,rejection_basis='SOURCE_NAME_ROLE_'+role.upper())
    # Recheck provider mappings as well as new candidates: a newly supported
    # date format must never promote a registration date to a report date.
    for field in DATE_FIELDS:
        for item in result.get(field,[]):
            if item.get('field_association')=='LICENCE_LABEL_POSITION':
                continue  # Two-dimensional card columns override linear row text.
            wanted=date_value(item['value'])
            if not wanted['valid_format']:continue
            witnesses=[]
            for page in pages:
                for row in source_rows(page):
                    for match in re.finditer(DATE_PATTERN,row['text']):
                        value=date_value(match.group())
                        if (value['canonical_value'] or value['raw_value'])!=(wanted['canonical_value'] or wanted['raw_value']):continue
                        source=witness(match.group(),row,'DATE_ROLE_WITNESS')
                        if not source or source['page_number']!=item.get('page_number'):continue
                        box=item.get('bounding_box',{});sb=source['bounding_box']
                        distance=abs(box.get('x0',sb['x0'])-sb['x0'])+abs(box.get('y0',sb['y0'])-sb['y0'])
                        witnesses.append((distance,date_role(row['text'][:match.start()])))
            if witnesses:
                role=min(witnesses,key=lambda pair:pair[0])[1]
                if role and role!=field:item.update(role_conflict=True,rejection_basis='SOURCE_DATE_ROLE_'+role.upper())
    # A label can end one OCR row while a source-bound full name spans the next.
    # Keep the complete witness and retain the partial span as rejected evidence.
    for item in result.get('patient_name',[]):
        if item.get('field_association')!='SCHEMA_LABEL_BOUNDARY':continue
        key=name_key(item['value'])
        for other in result.get('patient_name',[]):
            full=name_key(other['value'])
            if (other is not item and not other.get('role_conflict') and other.get('page_number')==item.get('page_number')
                and other.get('evidence_reference') and full.startswith(key+' ')):
                ib=item.get('bounding_box',{});ob=other.get('bounding_box',{})
                if ib and ob and abs((ib['y0']+ib['y1']-ob['y0']-ob['y1'])/2)<=2*max(1,ob['y1']-ob['y0']):
                    item.update(role_conflict=True,rejection_basis='WRAPPED_NAME_TRUNCATION');break
    if kind=='DRIVING_LICENSE':
        for field in ['patient_dob','license_expiry_date']:
            direct=[item for item in result.get(field,[]) if item.get('field_association')=='LICENCE_LABEL_POSITION']
            for item in result.get(field,[]):
                if direct and item.get('field_association')!='LICENCE_LABEL_POSITION' and not any(
                    item['value']==value['value'] for value in direct):
                    item.update(role_conflict=True,rejection_basis='LICENCE_DATE_COLUMN_ROLE')
        names=[item for item in result.get('patient_name',[]) if item.get('field_association')=='LICENCE_LABEL_POSITION']
        for item in result.get('patient_name',[]):
            if names and not any(name_similarity(item['value'],name['value'])>=.90 for name in names):
                item.update(role_conflict=True,rejection_basis='LICENCE_PARENT_OR_NON_HOLDER_LABEL')
    return result,audit
