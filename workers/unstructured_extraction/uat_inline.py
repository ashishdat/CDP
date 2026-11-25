"""Recover explicit same-line UAT label values, including labels without a colon."""
import re

from packages.domain.common import BoundingBox
from packages.layout_intelligence.models import CanonicalLayoutCandidate, LabelValueLinkEvidence
from workers.unstructured_extraction.uat_validation import valid_scalar
from workers.unstructured_extraction.uat_values import DATE_FIELDS, DATE_PATTERN


def recover_inline(result, fields):
    recovered = {}
    for line in result.lines:
        for field, spec in fields.items():
            for alias in sorted(spec['aliases'], key=len, reverse=True):
                pattern=r'\b'+r'\s*'.join(re.escape(word) for word in alias.split())+r'\b\s*:?\s*(.+)'
                if alias=='name':
                    pattern=r'^\s*name\s*:\s*(.+)'
                match = re.search(pattern,line.text,re.IGNORECASE)
                if not match:
                    continue
                value = match.group(1).strip()
                if field in DATE_FIELDS:
                    date = re.match(DATE_PATTERN,value)
                    value = date.group() if date else ''
                else:
                    value = re.split(r'\b(?:collection date|collected(?: on| date)?|report(?:ed)?(?: on| date)?|received date|receiving time|registered(?: on)?|transaction id|patient id|referral|ref(?:erred)?\.? by|doctor name|cardiac electric|sex|gender|age)\b\s*:?\s*', value, flags=re.IGNORECASE)[0].strip()
                if not valid_scalar(field, value):
                    continue
                # The value region must not inherit confidence from unrelated
                # labels, dates or neighboring columns on the same OCR row.
                start=match.start(1);end=start+len(value);offset=0;tokens=[]
                for token in line.tokens:
                    left=offset;right=left+len(token.text);offset=right+1
                    if left<end and right>start: tokens.append(token)
                if not tokens: continue
                box=BoundingBox(x0=min(t.bbox.x0 for t in tokens),y0=min(t.bbox.y0 for t in tokens),
                    x1=max(t.bbox.x1 for t in tokens),y1=max(t.bbox.y1 for t in tokens),
                    image_width=line.bbox.image_width,image_height=line.bbox.image_height)
                evidence = LabelValueLinkEvidence(field_name=field, label_text=alias,
                    label_bbox=line.bbox, candidate_text=value, candidate_bbox=box,
                    horizontal_distance=0, vertical_distance=0, same_row=True, same_column=True,
                    datatype_valid=True, label_similarity=1, spatial_score=1,
                    total_score=1, relationship='EXPLICIT_INLINE_LABEL_VALUE')
                recovered.setdefault(field, []).append(CanonicalLayoutCandidate(
                    field_name=field, value=value, confidence=1, bbox=box,
                    original_label=alias, matched_alias=alias, mapping_confidence=1,
                    datatype_valid=True, relationship_evidence=evidence))
                break
    # A precise inline value supersedes this page's generic below-label guesses;
    # preserve all explicit alternatives so cross-page conflicts remain visible.
    result.candidates.update(recovered)
    return result
