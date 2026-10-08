"""All-page local evidence collection for unsupported claim bundles; no AUTO authority."""
from packages.recovery.independent_failures import classify_page_text, NON_CLAIM_CANDIDATES
from packages.extraction_recovery.unstructured_reg_fallback import _heuristic_fields_from_di_text
from workers.cascade.tesseract_adapter import TesseractTextExtractor


def recover_multipage_claim_review(images, *, extractor=None):
    if len(images)>12:
        return {"attempted":False,"reason":"BUNDLE_PAGE_LIMIT_REQUIRES_REVIEW","fields":{}}
    extractor=extractor or TesseractTextExtractor(psm=11,timeout_seconds=15)
    pages=[];by_field={}
    for number,image in enumerate(images,1):
        try:
            lines=extractor.extract(image)
        except Exception as exc:
            pages.append({"page_number":number,"status":"READER_ERROR","error_type":type(exc).__name__})
            continue
        text="\n".join(line.text for line in lines)
        role=classify_page_text(text)
        observed={"page_number":number,"status":"OBSERVED","role":role.value,
                  "reader_engine":"tesseract","text":text,
                  "lines":[{"text":line.text,"bbox":[line.x0,line.y0,line.x1,line.y1],"confidence":line.confidence} for line in lines]}
        pages.append(observed)
        if role in NON_CLAIM_CANDIDATES:
            continue  # Preserve attachments; never parse a separator as patient data.
        for field,value in _heuristic_fields_from_di_text(text).items():
            by_field.setdefault(field,[]).append({"value":value,"page_number":number,"shadow_review_only":True})
    fields={field:reads[0]["value"] for field,reads in by_field.items()
            if len({read["value"] for read in reads})==1}
    return {"attempted":True,"reason":"MULTIPAGE_LOCAL_EVIDENCE_REQUIRES_GOVERNED_REVIEW",
            "fields":fields,"candidates":by_field,"pages":pages,"page_count":len(images),
            "all_candidates_review_only":True,"acceptance_authority":"NONE",
            "critical_blockers":["patient_name","insured_name","patient_dob","insured_id_number","total_charge"]}
