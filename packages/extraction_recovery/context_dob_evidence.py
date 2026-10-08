"""Qualify blind context DOB reads against the existing recorded geometry."""
import re
from packages.extraction_recovery.spatial_dob import spatial_dob_components, observed_numeric_word
from packages.field_normalization import normalize_date

def qualify_context_dob(record,canonical_region):
    di=record.get("di") or {};claude=record.get("claude") or {}
    value=spatial_dob_components(tuple(di.get("words") or []))
    a,valid_a=normalize_date(value or "");b,valid_b=normalize_date(claude.get("value") or "")
    if not(valid_a and valid_b and a==b):return {"qualified":False,"reason":"PROVIDER_AGREEMENT_NOT_ESTABLISHED","di_value":value}
    # All numeric date words must be localized in the existing safe region.
    # A context crop does not silently expand the field's geometry authority.
    numeric=[w for w in di["words"] if re.fullmatch(r"[0-9]{2}|[0-9]{4}",observed_numeric_word(w.get("content")))]
    if len(numeric) not in {2,3}:return {"qualified":False,"reason":"DATE_WORD_LOCALIZATION_AMBIGUOUS","di_value":value}
    ox,oy=record["context_bbox"][:2];points=[w.get("polygon")or[]for w in numeric]
    if any(len(p)!=8 for p in points):return {"qualified":False,"reason":"DATE_WORD_POLYGON_MISSING","di_value":value}
    xs=[float(x)+ox for p in points for x in p[::2]];ys=[float(y)+oy for p in points for y in p[1::2]]
    observed=[min(xs),min(ys),max(xs),max(ys)];x0,y0,x1,y1=canonical_region
    if not(x0<=observed[0]<observed[2]<=x1 and y0<=observed[1]<observed[3]<=y1):
        return {"qualified":False,"reason":"OBSERVED_DATE_OUTSIDE_RECORDED_CELL","di_value":value,"observed_bbox":observed}
    return {"qualified":True,"reason":"BLIND_AGREEMENT_WITH_OBSERVED_IN_CELL_WORDS","di_value":value,"observed_bbox":observed}
