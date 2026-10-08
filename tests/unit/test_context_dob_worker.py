from dataclasses import dataclass
from types import SimpleNamespace
from PIL import Image
from workers.cascade.context_dob_recovery import recover_context_dob
from tests.unit.test_context_dob_words import inputs
from packages.extraction_recovery.gpt4o_crop_residual import Gpt4oCropResidualResult

class Backend:
 def analyze(self,data):return SimpleNamespace(text="MM DD YY 0130 1965",words=inputs(),confidence=.95)
class Claude:
 def recognize_fields(self,crops,**kwargs):
  assert kwargs["prior_candidates"]=={"patient_dob":[]}
  return {"patient_dob":Gpt4oCropResidualResult(True,True,False,"01/30/1965","01/30/1965",True,False,"CLAUDE_SHAPED",engine="anthropic_claude_crop",confidence=.96)}
def test_blind_context_proposes_evidence_without_acceptance_or_fake_crop():
 row={"canonical_region":[672,420,883,465],"candidates":[],"attempts":[],"cascade":{"accepted":False}}
 result=recover_context_dob(row,Image.new("L",(1712,2216),255),di_engine=SimpleNamespace(_backend=Backend()),claude_engine=Claude())
 assert len(result["candidates"])==2 and not result["cascade"]["accepted"]
 assert result["candidates"][0]["bounding_box"]["y0"]==380
 assert result["context_dob_recovery"]["qualification"]["observed_bbox"]==[683.0,433.0,861.0,461.0]
 assert not row["candidates"]
 assert recover_context_dob(result,Image.new("L",(1712,2216)),di_engine=None,claude_engine=None)==result
