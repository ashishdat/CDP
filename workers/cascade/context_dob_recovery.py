"""Bounded blind DI/Claude recovery; only observed in-cell agreement is eligible."""
import io,hashlib
from dataclasses import asdict
from packages.settings import Settings
from packages.extraction_recovery.context_dob_evidence import qualify_context_dob
from packages.extraction_recovery.gpt4o_crop_residual import _AzureGpt4oCropRecognizer
from workers.cascade.azure_di_factory import build_azure_read_engine

def recover_context_dob(row,image,*,di_engine=None,claude_engine=None,local_reader=None):
    updated={**row,"candidates":list(row.get("candidates")or[]),"attempts":list(row.get("attempts")or[])}
    if updated.get("context_dob_recovery"):return updated
    if claude_engine is None and not Settings().anthropic_crop_residual_enabled:
        updated["context_dob_recovery"]={"qualification":{"qualified":False,"reason":"CLAUDE_CONTEXT_DISABLED"}}
        return updated
    x0,y0,x1,y1=map(int,row["canonical_region"])
    context=(max(0,x0-72),max(0,y0-40),min(image.width,x1+67),min(image.height,y1+55))
    crop=image.crop(context);data=io.BytesIO();crop.save(data,format="PNG")
    record={"field":"patient_dob","context_bbox":context,"prior_hints_supplied":False,"input_sha256":hashlib.sha256(data.getvalue()).hexdigest()}
    record.update(getattr(image,'_cdp_source_identity',{}))
    try:
        di=di_engine or build_azure_read_engine(Settings())
        evidence=di._backend.analyze(data.getvalue())
        record["di"]={"text":evidence.text,"words":evidence.words,"confidence":evidence.confidence}
        claude=claude_engine or _AzureGpt4oCropRecognizer(provider="claude")
        result=claude.recognize_fields({"patient_dob":crop},field_types={"patient_dob":"date"},
            descriptions={"patient_dob":"Read ONLY patient birth date in field 3 beneath MM DD YY. Do not infer missing digits or use other dates; abstain if unclear."},prior_candidates={"patient_dob":[]})["patient_dob"]
        record["claude"]=asdict(result)
        qualification=qualify_context_dob(record,row["canonical_region"])
        record["qualification"]=qualification
        if qualification["qualified"]:
            for provider,engine,model in [("di","azure_document_intelligence_read","prebuilt-read"),("claude","anthropic_claude_crop","claude-sonnet-4-6")]:
                observed=record[provider];cx0,cy0,cx1,cy1=context
                candidate={"value":qualification["di_value"],"raw_value":observed.get("text")or observed.get("raw_value")or observed.get("value"),"engine":engine,"model_name":model,"model_version":"unknown",
                    "preprocessing_variant":"blind_context_read","preprocessing_version":"context-field-evidence-v1","raw_confidence":observed.get("confidence")or 0.0,"calibrated_confidence":None,
                    "bounding_box":{"x0":cx0,"y0":cy0,"x1":cx1,"y1":cy1,"image_width":image.width,"image_height":image.height},"latency_ms":0.0,"validation_results":observed.get("validation_results",[]),
                    "context_localization":qualification,"prior_hints_supplied":False}
                updated["candidates"].append(candidate)
                updated["attempts"].append({"engine":engine,"reason":"BLIND_CONTEXT_DATE_OBSERVED","observation":{"text":candidate["raw_value"]},"input_context_bbox":context,"field_value_bbox":qualification["observed_bbox"]})
        if local_reader is not None:
            from packages.extraction_recovery.localized_dob_reader import read_localized_dob
            local,attempts=read_localized_dob(image,record,row['canonical_region'],local_reader)
            updated['attempts'].extend(attempts)
            if local:
                local['bounding_box']={'x0':x0,'y0':y0,'x1':x1,'y1':y1,'image_width':image.width,'image_height':image.height}
                local['latency_ms']=0.0
                updated['candidates'].append(local)
    except Exception as exc:
        record["qualification"]={"qualified":False,"reason":"CONTEXT_PROVIDER_FAILURE","error_type":type(exc).__name__}
    finally:crop.close()
    # This is acquisition only. Never mark the cascade or field accepted.
    updated["context_dob_recovery"]=record
    from packages.extraction_recovery.dob_confirmation import dob_component_conflicts
    updated['dob_component_conflicts']=dob_component_conflicts(updated['candidates'],updated['attempts'])
    from packages.extraction_recovery.dob_recovery_contract import plan_recovery,qualify_value_row
    updated['dob_geometry_proof']=qualify_value_row(record,row['canonical_region'])
    updated['dob_recovery_plan']=plan_recovery(updated['candidates'],updated['attempts'],geometry_qualified=bool(record.get('source_sha256') and updated['dob_geometry_proof']['qualified']))
    return updated
