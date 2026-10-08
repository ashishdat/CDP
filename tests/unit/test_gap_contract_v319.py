from dataclasses import replace
from packages.ocr.evidence_eligibility import confirmation_eligible
from packages.claim_evidence.line_sum_authority import box28_di_partner_confirmed, line_has_dual_engine_agreement
from packages.extraction_recovery.cloud_stop_ladder import charge_locals_settled
from packages.extraction_recovery.dob_confirmation import dob_component_conflicts, dob_reads_confirmed


def test_nested_hint_and_shadow_flags_cannot_be_lost():
    for flag in ("prior_hints_supplied", "shadow_review_only"):
        assert not confirmation_eligible({"ocr_candidate": {"engine": "rapidocr", flag: True}})
        assert not confirmation_eligible({flag: True, "ocr_candidate": {"engine": "rapidocr"}})


def test_financial_raw_helpers_do_not_count_hinted_cloud_echo():
    di = {"engine":"azure_document_intelligence_read", "value":"600.00"}
    vision = {"engine":"anthropic_claude_crop", "value":"600.00", "prior_hints_supplied":True}
    assert not box28_di_partner_confirmed("600.00", [di,vision])
    assert box28_di_partner_confirmed("600.00", [di,{**vision,"prior_hints_supplied":False}])


def test_review_only_second_local_reader_cannot_mint_line_consensus_or_stop_acquisition():
    local = {"engine":"paddleocr", "value":"600.00"}
    shadow = {"engine":"rapidocr", "value":"600.00", "shadow_review_only":True}
    assert not line_has_dual_engine_agreement({"charges":"600.00","candidates":[local,shadow]})
    assert not charge_locals_settled([local,shadow], observed_line_charges=["600.00"])
    assert line_has_dual_engine_agreement({"charges":"600.00","candidates":[local,{**shadow,"shadow_review_only":False}]})


def test_later_complete_read_from_same_engine_does_not_erase_earlier_partial_conflict():
    candidates=[{"engine":"rapidocr","value":"05/30/1947"}, {"engine":"paddleocr","value":"05/30/1947"}]
    attempts=[{"engine":"rapidocr","observation":{"parts":{"DD":"20"}}},
              {"engine":"rapidocr","observation":{"parts":{"MM":"05","DD":"30","YY":"1947"}}}]
    assert dob_component_conflicts(candidates,attempts) == [{"engine":"rapidocr","component":"DD","observed":"20"}]
    assert not dob_reads_confirmed(candidates,attempts)


def test_review_only_complete_date_does_not_confirm_single_native_reader():
    candidates=[{"engine":"rapidocr","value":"05/30/1947"},
        {"engine":"trocr","value":"05/30/1947","shadow_review_only":True}]
    assert not dob_reads_confirmed(candidates)



def test_hinted_local_amount_cannot_stop_di_confirmation():
    from packages.extraction_recovery.gpt4o_crop_residual import _charge_local_disagrees_with_di
    candidates=[{"engine":"azure_document_intelligence_read","value":"600.00"},
        {"engine":"rapidocr","value":"600.00","prior_hints_supplied":True}]
    assert _charge_local_disagrees_with_di(candidates)



def test_geometry_promotion_does_not_create_rapidocr_reader_or_confidence():
    from packages.claim_evidence.line_charge_selector import _geometry_cents_candidate_from_attempts
    line={"canonical_region":[100,100,200,130],"attempts":[{
        "engine":"tesseract","reason":"GEOMETRY_CENTS_CONFIRMED", "observation":{
            "canonical_monetary_value":"600.00", "raw_digit_sequence":"60000"}}]}
    result=_geometry_cents_candidate_from_attempts(line)
    assert result["engine"] == "tesseract"
    assert result["raw_confidence"] == 0
    assert result["calibrated_confidence"] is None


def test_service_line_selector_excludes_review_only_amount():
    from packages.claim_evidence.line_charge_selector import select_line_charge
    line={"canonical_region":[100,100,200,130],"candidates":[
        {"engine":"rapidocr","value":"600.00","raw_value":"600.00","shadow_review_only":True}]}
    result=select_line_charge(line)
    assert result.amount is None



def test_contended_lock_has_a_finite_wait_and_preserves_file_position(monkeypatch,tmp_path):
    import errno, os, time
    from packages.file_lock import lock_exclusive
    def blocked(*args):
        raise OSError(errno.EACCES,"controlled contention")
    if os.name == "nt":
        import msvcrt
        monkeypatch.setattr(msvcrt,"locking",blocked)
    else:
        import fcntl
        monkeypatch.setattr(fcntl,"flock",blocked)
    with (tmp_path/"lock").open("a+") as handle:
        handle.write("abcdef");handle.flush();position=handle.tell();started=time.monotonic()
        import pytest
        with pytest.raises(TimeoutError, match="EXCLUSIVE_LOCK_WAIT_EXHAUSTED"):
            lock_exclusive(handle,timeout_seconds=.01)
        assert time.monotonic()-started < 1
        assert handle.tell() == position


def test_vlm_lock_passes_a_bounded_wait_to_the_shared_lock(monkeypatch,tmp_path):
    import packages.file_lock as module
    from packages.extraction_recovery.vlm_crop_lock import vlm_crop_lock
    waits=[]
    monkeypatch.setenv("CDP_VLM_CROP_LOCK","1")
    monkeypatch.setenv("CDP_VLM_CROP_LOCK_PATH",str(tmp_path/"vision.lock"))
    monkeypatch.setenv("CDP_VLM_CROP_LOCK_TIMEOUT_SECONDS","7")
    monkeypatch.setattr(module,"lock_exclusive",lambda handle,**kwargs: waits.append(kwargs["timeout_seconds"]))
    monkeypatch.setattr(module,"unlock",lambda handle:None)
    with vlm_crop_lock():
        with vlm_crop_lock():
            pass
    assert waits == [7]



def test_di_slot_wait_refuses_transaction_that_cannot_fit_deadline(tmp_path):
    from workers.cascade.azure_di_backend import wait_for_azure_di_slot
    import pytest
    slot=tmp_path/"di-slot";slot.write_text("100")
    sleeps=[]
    with pytest.raises(TimeoutError,match="SLOT_EXCEEDS_OPERATION_BUDGET"):
        wait_for_azure_di_slot(interval_seconds=60,sleeper=sleeps.append,now=lambda:101,
            slot_path=slot,remaining_seconds=lambda:10)
    assert sleeps == []
    assert slot.read_text() == "100"


def test_di_backoff_cannot_overshoot_operation_budget():
    from workers.cascade.azure_di_backend import AzureDocumentIntelligenceReadBackend
    import pytest,time
    sleeps=[]
    backend=AzureDocumentIntelligenceReadBackend(endpoint="https://example.invalid",api_key="not-a-credential",sleeper=sleeps.append)
    token=backend._operation_deadline.set(time.monotonic()+2)
    try:
        with pytest.raises(TimeoutError,match="RETRY_EXCEEDS_OPERATION_BUDGET"):
            backend._budgeted_sleep(55)
    finally:
        backend._operation_deadline.reset(token)
    assert sleeps == []


def test_generic_bundle_review_never_merges_pages_into_auto_authority(monkeypatch):
    from types import SimpleNamespace
    from PIL import Image
    import packages.recovery.multipage_claim_review as module
    monkeypatch.setattr(module,"_heuristic_fields_from_di_text",lambda text: {"total_charge":"600.00"} if "CHARGE" in text else {})
    class Reader:
        def extract(self,image):
            text="Document Separator" if image.getpixel((0,0))==0 else "TOTAL CHARGE 600.00"
            return [SimpleNamespace(text=text,x0=1,y0=1,x1=10,y1=10,confidence=.8)]
    result=module.recover_multipage_claim_review([Image.new("L",(20,20),0),Image.new("L",(20,20),255)],extractor=Reader())
    assert result["fields"]["total_charge"] == "600.00"
    assert result["candidates"]["total_charge"][0]["page_number"] == 2
    assert result["all_candidates_review_only"]
    assert result["acceptance_authority"] == "NONE"
    assert len(result["pages"]) == 2



def test_generic_bundle_local_reader_has_per_page_timeout(monkeypatch):
    from types import SimpleNamespace
    from PIL import Image
    import workers.cascade.tesseract_adapter as module
    waits=[]
    def run(*args,**kwargs):
        waits.append(kwargs["timeout"])
        return SimpleNamespace(stdout=b"level\ttext\tconf\tleft\ttop\twidth\theight\n",returncode=0)
    monkeypatch.setattr(module.subprocess,"run",run)
    module.TesseractTextExtractor(timeout_seconds=15).extract(Image.new("L",(10,10),255))
    assert waits == [15]


def test_geometry_near_miss_proposal_never_ignores_unsafe_transform(monkeypatch):
    from dataclasses import replace
    from PIL import Image
    from workers.page_detection import template_selector as module
    from workers.page_detection.template_alignment import _failure
    from packages.templates.registry import TemplateRegistry
    monkeypatch.setattr(module,"compute_grid_signature",lambda image:None)
    monkeypatch.setattr(module,"signature_similarity",lambda *args:0)
    def align(*args,**kwargs):
        failure=_failure("sift","insufficient_inliers,unsafe_scale_change")
        return replace(failure,alignment_score=.6,evidence=failure.evidence.model_copy(update={"corner_validity":True}))
    monkeypatch.setattr(module,"align_to_reference",align)
    result=module.TemplateSelector(TemplateRegistry.load_from_directory()).select([Image.new("L",(64,64),255)],text_lines={})
    assert result.template_id is None



def test_expired_document_budget_never_starts_another_vision_call(monkeypatch,tmp_path):
    from types import SimpleNamespace
    import packages.extraction_recovery.doc_latency_budget as budget
    from packages.extraction_recovery.vlm_crop_lock import vlm_crop_lock
    import pytest
    monkeypatch.setattr(budget,"get_doc_budget",lambda:SimpleNamespace(elapsed=lambda:211))
    monkeypatch.setenv("CDP_VLM_CROP_LOCK","1")
    monkeypatch.setenv("CDP_CLOUD_RECOVERY_DEADLINE_SECONDS","210")
    monkeypatch.setenv("CDP_VLM_CROP_LOCK_PATH",str(tmp_path/"lock"))
    with pytest.raises(TimeoutError,match="VLM_CROP_RECOVERY_BUDGET_EXHAUSTED"):
        with vlm_crop_lock():
            raise AssertionError("must not start another network reader")



def test_candidate_cache_changes_with_field_rules_and_ocr_observations(tmp_path):
    from dataclasses import replace
    from PIL import Image
    from workers.field_candidates.pipeline import CandidateStore
    from workers.field_candidates.contracts import PreparedPage,FieldSpec
    from workers.field_candidates.providers import PsychologicalReceiptProvider
    from workers.page_detection.text_extraction import TextLine
    store=CandidateStore(tmp_path);provider=PsychologicalReceiptProvider()
    page=PreparedPage(1,Image.new("L",(100,100),255),"same",(),{"psychological_receipt":.9})
    field=FieldSpec("patient_name","person_name",True,anchors=("client",))
    key=store.cache_path(page,provider,field)
    assert key != store.cache_path(page,provider,replace(field,anchors=("patient",)))
    assert key != store.cache_path(replace(page,page_number=2),provider,field)
    assert key != store.cache_path(replace(page,text_lines=(TextLine("JANE DOE",1,1,20,10,.9),)),provider,field)


def test_cached_candidate_is_rebound_to_current_document(tmp_path):
    from tests.unit.cases.test_candidate_pipeline import _document
    from PIL import Image
    from workers.field_candidates.pipeline import AllPageCandidatePipeline,CandidateStore
    from workers.field_candidates.contracts import PreparedPage,FieldSpec
    from workers.field_candidates.providers import PsychologicalReceiptProvider
    class Provider(PsychologicalReceiptProvider):
        calls=0
        def extract_candidates(self,*args):
            self.calls+=1
            return super().extract_candidates(*args)
    provider=Provider();pipeline=AllPageCandidatePipeline([provider],CandidateStore(tmp_path))
    page=PreparedPage(1,Image.new("L",(100,100),255),"same",(),{"psychological_receipt":.9})
    fields=[FieldSpec("name","text",False)]
    first=_document();second=_document()
    pipeline.run(first,[page],fields)
    candidates,_=pipeline.run(second,[page],fields)
    assert provider.calls == 1
    assert candidates[0].document_id == str(second.document_id)


def test_transient_provider_failure_is_retried_on_resume(tmp_path):
    from tests.unit.cases.test_candidate_pipeline import _document
    from PIL import Image
    from workers.field_candidates.pipeline import AllPageCandidatePipeline,CandidateStore
    from workers.field_candidates.contracts import PreparedPage,FieldSpec,CandidateStatus
    from workers.field_candidates.providers import PsychologicalReceiptProvider
    class Provider(PsychologicalReceiptProvider):
        calls=0
        def extract_candidates(self,*args):
            self.calls+=1
            if self.calls==1:raise TimeoutError("controlled reader timeout")
            return super().extract_candidates(*args)
    provider=Provider();pipeline=AllPageCandidatePipeline([provider],CandidateStore(tmp_path))
    page=PreparedPage(1,Image.new("L",(100,100),255),"same",(),{"psychological_receipt":.9})
    fields=[FieldSpec("name","text",False)];document=_document()
    first,_=pipeline.run(document,[page],fields)
    second,_=pipeline.run(document,[page],fields)
    assert first[0].status == CandidateStatus.PROVIDER_ERROR
    assert second[0].status == CandidateStatus.NO_EVIDENCE
    assert provider.calls == 2


def test_malformed_candidate_cache_requests_fresh_inference(tmp_path):
    from workers.field_candidates.pipeline import CandidateStore
    path=tmp_path/"corrupt.json";path.write_text("{incomplete")
    assert CandidateStore(tmp_path).load(path) is None
