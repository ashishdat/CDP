"""Source-preserving date/identifier representations; no hidden digits or years."""
import re
from datetime import datetime

DATE_FIELDS={'patient_dob','report_date','examination_date','license_expiry_date'}
FORM_LABELS={'life assured','registered on','reported on','collected on','doctor name',
             'patient name','full name of life assured','date of birth','age gender',
             'medical examination report','name of proposer','father name',
             'name','male','female','gender','age','date','unknown','nil','mr','mrs','ms','dr'}
DATE_PATTERN=r'(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*(?:\d{4}|\d{2}))(?!\d)'
DATE_PATTERN=r'(?:'+DATE_PATTERN+r'|\d{1,2}\s+\d{1,2}\s+\d{4})(?!\d)'
MONTH=r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
DATE_PATTERN=r'(?i:(?:'+DATE_PATTERN+r'|\d{1,2}[ -]'+MONTH+r'[ -]\d{4}|'+MONTH+r'\s+\d{1,2},?\s+\d{4}))(?!\d)'


def date_value(value, references=()):
    raw=' '.join(value.split()).strip(' :')
    cleaned=re.sub(r'\s*([/.-])\s*',r'\1',raw)
    if re.fullmatch(r'\d{1,2}\s+\d{1,2}\s+\d{4}',cleaned):
        cleaned='/'.join(cleaned.split())
    for fmt in ('%d/%m/%Y','%d-%m-%Y','%Y-%m-%d','%d.%m.%Y',
                '%d-%b-%Y','%d-%B-%Y','%d %b %Y','%d %B %Y',
                '%b %d, %Y','%B %d, %Y','%b %d %Y','%B %d %Y'):
        try:
            parsed=datetime.strptime(cleaned,fmt).date()  # noqa: DTZ007 - date-only source value
            return {'raw_value':raw,'canonical_value':parsed.isoformat(),'valid_format':True,'year_ambiguous':False}
        except ValueError:
            pass
    match=re.fullmatch(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{2})',cleaned)
    if match:
        day,month,year=map(int,match.groups())
        try:
            datetime(2000+year,month,day)  # noqa: DTZ001 - calendar validity only; not a century inference
        except ValueError:
            return {'raw_value':raw,'canonical_value':None,'valid_format':False,'year_ambiguous':False}
        matches=set()
        for ref in references:
            item=date_value(ref)
            if item['canonical_value']:
                d=datetime.fromisoformat(item['canonical_value']).date()
                if d.day==day and d.month==month and d.year%100==year:
                    matches.add(item['canonical_value'])
        canonical=next(iter(matches)) if len(matches)==1 else None
        return {'raw_value':raw,'canonical_value':canonical,'valid_format':True,'year_ambiguous':canonical is None}
    return {'raw_value':raw,'canonical_value':None,'valid_format':False,'year_ambiguous':False}


def identity_value(value):
    raw=' '.join(value.split()).strip()
    compact=re.sub(r'\s+','',raw).upper()
    if re.fullmatch(r'[2-9]\d{11}',compact):
        return {'kind':'full_aadhaar','raw_value':raw,'canonical_value':compact,'visible_suffix':compact[-4:]}
    if re.fullmatch(r'[A-Z]{5}\d{4}[A-Z]',compact):
        return {'kind':'full_pan','raw_value':raw,'canonical_value':compact,'visible_suffix':None}
    if re.fullmatch(r'[X*•●#]{8}\d{4}',compact):
        return {'kind':'masked_aadhaar','raw_value':raw,'canonical_value':None,'visible_suffix':compact[-4:]}
    return {'kind':'unresolved','raw_value':raw,'canonical_value':None,'visible_suffix':None}


def label_only(value):
    text=' '.join(re.sub(r'[^a-z ]',' ',value.casefold()).split())
    return text in FORM_LABELS
