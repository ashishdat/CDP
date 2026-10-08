from packages.extraction_recovery.context_dob_evidence import qualify_context_dob
from tests.unit.test_context_dob_words import inputs

def record():return {"context_bbox":[600,380,950,520],"di":{"words":inputs()},"claude":{"value":"01/30/1965"}}
def test_agreement_requires_observed_words_inside_recorded_geometry():
 result=qualify_context_dob(record(),[672,420,883,465]);assert result["qualified"]
 assert result["observed_bbox"]==[683.0,433.0,861.0,461.0]
def test_context_cannot_override_crop_authority():
 assert not qualify_context_dob(record(),[672,420,883,450])["qualified"]
def test_vision_value_cannot_overrule_independent_disagreement():
 r=record();r["claude"]["value"]="01/30/1966"
 assert not qualify_context_dob(r,[672,420,883,465])["qualified"]

def test_actual_pipe_words_keep_original_polygons_for_localization():
 from tests.unit.test_context_dob_words import word
 r={'context_bbox':[600,380,950,520],'di':{'words':[word('02|',108,145,39,72),word('02',158,184,43,71),word('|1990',190,266,44,71)]},'claude':{'value':'02/02/1990'}}
 assert not qualify_context_dob(r,[672,420,883,465])['qualified']  # observed top 419 is outside the cell
 assert qualify_context_dob(r,[672,419,883,465])['qualified']
