"""Case completeness includes declared document roles, not only saved assets."""
from workers.unstructured_extraction.extraction_acceptance import normalized

IDENTITY_ROLES={'AADHAAR':'identity:aadhaar','PAN':'identity:pan',
                'IDENTITY_PROOF':'identity:any','DRIVING_LICENSE':'identity:driving_license'}


def decide_case(documents):
    required={IDENTITY_ROLES[doc['declared_type']] for doc in documents if doc['declared_type'] in IDENTITY_ROLES}
    provided={role for doc in documents for role in doc['decision'].get('provided_roles',[])}
    unresolved=[doc['id'] for doc in documents if not doc['decision']['extraction_stp_eligible']]
    supply_flags=sorted({('PAN_NOT_SUPPLIED' if doc['declared_type']=='PAN' else 'LICENCE_NOT_SUPPLIED')
        for doc in documents if doc['declared_type'] in {'PAN','DRIVING_LICENSE'}
        and doc.get('effective_type')=='PERSON_PHOTO' and IDENTITY_ROLES[doc['declared_type']] not in provided
        and not any(other.get('effective_type')==doc['declared_type'] and
            (other.get('decision',{}).get('document_type_evidence') or other.get('type_resolution',{}).get('licence_card_supplied'))
            for other in documents)})
    conflicts={}
    for field in ['patient_name','patient_dob']:
        values={normalized(field,item['value']) for doc in documents
            if (item:=doc['decision']['extracted_fields'].get(field))}
        if len(values)>1: conflicts[field]=sorted(values)
    return {'case_complete':not unresolved and not (required-provided),
        'required_roles':sorted(required),'provided_roles':sorted(provided),
        'missing_roles':sorted(required-provided),'unresolved_documents':unresolved,
        'supply_flags':supply_flags,
        'portrait_identity_placeholders':[doc['id'] for doc in documents
            if doc['declared_type'] in IDENTITY_ROLES and doc.get('effective_type')=='PERSON_PHOTO'],
        'cross_document_identity_conflicts':conflicts,
        'cross_document_identity_status':'DIAGNOSTIC_ONLY_REQUIRES_REVIEWED_CONTRACT',
        'underwriting_approval':False,'correctness_verified':False}
