"""Source-bound observation reuse and explicit DOB recovery states; no acceptance."""
from dataclasses import dataclass,asdict
from enum import StrEnum
import hashlib,json,math
import re
from packages.field_normalization import normalize_date
from packages.ocr.evidence_eligibility import eligible_candidates
from packages.extraction_recovery.dob_confirmation import dob_component_conflicts,dob_reads_confirmed

class RecoveryState(StrEnum):
    NEEDS_GEOMETRY='NEEDS_GEOMETRY'
    NEEDS_READ='NEEDS_READ'
    NEEDS_CONFIRMATION='NEEDS_CONFIRMATION'
    FULL_DATE_CONFLICT='FULL_DATE_CONFLICT'
    PARTIAL_COMPONENT_CONFLICT='PARTIAL_COMPONENT_CONFLICT'
    READY_FOR_POLICY='READY_FOR_EXISTING_POLICY'
    BUDGET_EXHAUSTED='BUDGET_EXHAUSTED'

def qualify_value_row(record,canonical):
    """Geometry is independent of whether DI and Claude agree on a date."""
    words=[w for w in (record.get('di') or {}).get('words',[]) if re.fullmatch(r'[0-9]{1,4}',str(w.get('content') or ''))]
    if len(words)!=3:return {'qualified':False,'reason':'VALUE_ROW_WORD_GEOMETRY_INCOMPLETE'}
    origin=record.get('context_bbox')
    if not origin or len(origin)!=4:return {'qualified':False,'reason':'CONTEXT_FRAME_MISSING'}
    boxes=[]
    for word in words:
        p=word.get('polygon') or []
        if len(p)!=8 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in p):return {'qualified':False,'reason':'VALUE_POLYGON_INVALID'}
        b=(min(p[::2])+origin[0],min(p[1::2])+origin[1],max(p[::2])+origin[0],max(p[1::2])+origin[1])
        if not(canonical[0]<=b[0]<b[2]<=canonical[2] and canonical[1]<=b[1]<b[3]<=canonical[3]):return {'qualified':False,'reason':'VALUE_INK_OUTSIDE_RECORDED_CELL'}
        boxes.append(b)
    boxes.sort()
    if any(a[2]>b[0] for a,b in zip(boxes,boxes[1:])) or max(b[1] for b in boxes)>=min(b[3] for b in boxes):return {'qualified':False,'reason':'VALUE_ROW_AMBIGUOUS'}
    return {'qualified':True,'reason':'OBSERVED_ORDERED_VALUE_WORDS_IN_REGISTERED_CELL','component_boxes':boxes,'acceptance_authority':'NONE'}

def plan_recovery(candidates,attempts,*,geometry_qualified,remaining_reads=1):
    dates={}
    for candidate in eligible_candidates(candidates):
        value,valid=normalize_date(str(candidate.get('value') or ''))
        if valid:dates.setdefault(value,[]).append(candidate)
    conflicts={value:dob_component_conflicts([{'value':value,'engine':'diagnostic'}],attempts) for value in dates}
    blockers=[]
    if not geometry_qualified:blockers.append('GEOMETRY_NOT_QUALIFIED')
    if len(dates)>1:blockers.append('COMPLETE_DATE_DISAGREEMENT')
    if any(conflicts.values()):blockers.append('COMPONENT_DISAGREEMENT')
    if not geometry_qualified:state=RecoveryState.NEEDS_GEOMETRY
    elif len(dates)>1:state=RecoveryState.FULL_DATE_CONFLICT
    elif any(conflicts.values()):state=RecoveryState.PARTIAL_COMPONENT_CONFLICT
    elif not dates:state=RecoveryState.NEEDS_READ
    elif not dob_reads_confirmed(candidates,attempts):state=RecoveryState.NEEDS_CONFIRMATION
    else:state=RecoveryState.READY_FOR_POLICY
    if remaining_reads<=0 and state in {RecoveryState.NEEDS_READ,RecoveryState.NEEDS_CONFIRMATION}:state=RecoveryState.BUDGET_EXHAUSTED
    next_action={RecoveryState.NEEDS_GEOMETRY:'QUALIFY_VALUE_ROW_GEOMETRY',RecoveryState.NEEDS_READ:'BLIND_LOCAL_READ',
        RecoveryState.NEEDS_CONFIRMATION:'ACQUIRE_MISSING_POLICY_EVIDENCE',RecoveryState.FULL_DATE_CONFLICT:'REVIEW_LITERAL_RIVALS',
        RecoveryState.PARTIAL_COMPONENT_CONFLICT:'REVIEW_COMPONENT_GEOMETRY_AND_LITERAL',RecoveryState.READY_FOR_POLICY:'EXISTING_FIELD_DECISION',
        RecoveryState.BUDGET_EXHAUSTED:'HUMAN_REVIEW'}[state]
    return {'state':state.value,'next_action':next_action,'blocking_mechanisms':blockers,
        'complete_dates':sorted(dates),'component_conflicts_by_date':conflicts,
        'acceptance_authority':'NONE','readiness_is_not_policy_acceptance':True}

@dataclass(frozen=True)
class ObservationKey:
    source_sha256:str
    page_number:int
    field:str
    frame_sha256:str
    bbox:tuple
    pixels_sha256:str
    reader:str
    profile:str

    def __post_init__(self):
        for value in (self.source_sha256,self.frame_sha256,self.pixels_sha256):
            if len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('SHA256 identity required')
        if type(self.page_number)!=int or self.page_number<1:raise ValueError('Positive source page required')
        if len(self.bbox)!=4 or not all(math.isfinite(v) for v in self.bbox) or not(self.bbox[0]<self.bbox[2] and self.bbox[1]<self.bbox[3]):raise ValueError('Valid finite crop required')
        if not self.reader or not self.profile or not self.field:raise ValueError('Reader/profile/field required')

@dataclass(frozen=True)
class LiteralObservation:
    observation_id:str
    text:str
    raw_confidence:float|None
    calibrated_confidence:None=None

class ObservationLedger:
    def __init__(self):self._observations={}
    def observe(self,key,read):
        identity=hashlib.sha256(json.dumps(asdict(key),sort_keys=True).encode()).hexdigest()
        if identity in self._observations:return self._observations[identity],False
        text,score=read()
        if score is not None and (not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1):raise ValueError('Invalid raw confidence')
        result=LiteralObservation(identity,str(text or ''),score)
        self._observations[identity]=result
        return result,True
