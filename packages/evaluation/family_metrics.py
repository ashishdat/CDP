"""All-input family metrics and source-bound operator-label scoring."""
from collections import Counter,defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from packages.recovery.independent_failures import failure_category

ACCEPTED={"AUTO_ACCEPTED","REFERENCE_CONFIRMED"}
CRITICAL={"insured_name","patient_name","patient_dob","insured_id_number","total_charge","provider_npi","principal_diagnosis","federal_tax_no","type_of_bill"}

def canonical(value,field):
    text=str(value or "").strip().upper()
    if field == "total_charge":
        try:return str(Decimal(text.replace(",","").replace("$","")).normalize())
        except InvalidOperation:return text
    if field == "patient_dob":
        for fmt in ("%m/%d/%Y","%Y-%m-%d"):
            try:return datetime.strptime(text,fmt).date().isoformat()
            except ValueError:pass
    if field == "insured_id_number":
        # Separators and leading zeros are part of the observed identifier.
        # Removing them can hide an extraction error in verified scoring.
        return text
    # Punctuation-only normalization; preserve leading zeros and all initials.
    return re.sub(r"[^A-Z0-9]","",text)

def family_metrics(rows, *, selected_count=None, truth=None):
    unique={r.get("document") or r.get("claim_id"):r for r in rows if r.get("finished")}
    rows=list(unique.values()); groups=defaultdict(list)
    for row in rows:
        family=row.get("document_family") or ((row.get("unstructured_reg_fallback") or {}).get("route") or {}).get("family") or "UNKNOWN"
        groups[family].append(row)
    def scope(items,n):
        stp=sum(bool(r.get("completed") and r.get("true_stp")) for r in items)
        scored=false_accepts=unlabeled=unlabeled_all=missing_records=0; rejected_binding=0
        for row in items:
            label=(truth or {}).get("claims",{}).get(row.get("claim_id") or str(row.get("document","")).replace("/","__"),{})
            observed_hash=row.get("source_sha256") or row.get("document_id")
            bound=bool(label.get("source_sha256") and observed_hash == label["source_sha256"])
            if label and not bound:rejected_binding+=1
            observed_fields = row.get("fields") or {}
            if row.get("true_stp"):
                family = row.get("document_family") or "UNKNOWN"
                required = {"patient_name","patient_dob","insured_id_number","total_charge"}
                if family == "UB04":
                    required |= {"provider_npi","type_of_bill","principal_diagnosis","federal_tax_no"}
                missing_accepted = sum(name not in observed_fields or observed_fields[name].get("disp") not in ACCEPTED for name in required)
                missing_records += missing_accepted
            for name,field in observed_fields.items():
                if field.get("disp") not in ACCEPTED:continue
                expected=(label.get("fields") or {}).get(name,{})
                if not bound or expected.get("verification_status") != "OPERATOR_SUPPLIED_VERIFIED":
                    unlabeled_all+=1
                    unlabeled+=int(name in CRITICAL)
                    continue
                scored+=1
                false_accepts+=canonical(field.get("value"),name)!=canonical(expected.get("value"),name)
        return {"selected_count":n,"finished":len(items),"pending":max(0,n-len(items)),
            "completed":sum(bool(r.get("completed")) for r in items),"stp_count":stp,
            "stp_rate_of_all":stp/n if n else None,"failure_category_counts":dict(Counter(failure_category(r) for r in items)),
            "verified_accepted_fields_scored":scored,"verified_false_accepts":false_accepts,
            "unlabeled_accepted_critical_fields":unlabeled,"unlabeled_accepted_fields":unlabeled_all,"label_identity_rejections":rejected_binding,
            "missing_accepted_critical_field_records":missing_records,
            "zero_false_accepts_established":bool(scored and not false_accepts and not unlabeled_all and not missing_records and len(items)==n),
            "qualification":"Development results against source-bound operator-verified labels; partial coverage is not full-cohort accuracy."}
    return {"overall":scope(rows,selected_count if selected_count is not None else len(rows)),
        "by_family":{family:scope(items,len(items)) for family,items in sorted(groups.items())},
        "family_denominator_note":"Family strata include finished uniquely identified documents. Pending inputs have no inferred family; overall uses all selected inputs."}
