"""Literal compact UB04 birthdates; reject ambiguity and never infer missing year digits."""
import re
from datetime import date


def compact_birthdate(raw, *, as_of_date=None):
    text=str(raw or '').strip()
    if not re.fullmatch(r"[0-9]{7,8}",text):return None
    year=int(text[-4:]);limit=as_of_date or date.today()
    if not 1900 <= year <= limit.year:return None
    layouts=[(text[:2],text[2:4])] if len(text)==8 else [(text[:1],text[1:3]),(text[:2],text[2:3])]
    valid=set()
    for month,day in layouts:
        try:value=date(year,int(month),int(day))
        except ValueError:continue
        if value <= limit:valid.add(value.isoformat())
    # A short day is also compatible with a clipped multi-digit day. Permit
    # seven-digit normalization only for a unique one-digit-month reading.
    if len(text)==7:
        try:month_read=date(year,int(text[:1]),int(text[1:3])).isoformat()
        except ValueError:return None
        if month_read not in valid:return None
    return next(iter(valid)) if len(valid)==1 else None


def normalize_ub04_birthdate_candidates(field,candidates):
    if field not in {'patient_dob','date_of_birth'}:return candidates
    out=[]
    for original in candidates:
        candidate=dict(original);literal=str(candidate.get('value')or'').strip()
        raw=str(candidate.get('raw_value')or literal)
        normalized=compact_birthdate(literal)
        if normalized and re.search(r"(?<![0-9])"+re.escape(literal)+r"(?![0-9])",raw):
            candidate['value']=normalized
            candidate['normalization_rule']='UB04_UNIQUE_LITERAL_COMPACT_BIRTHDATE'
        out.append(candidate)
    return out
