from packages.extraction_recovery.independent_case_router import promote_unstructured_fields

def test_complete_valid_fields_are_not_an_acceptance_decision():
    disposition,blockers=promote_unstructured_fields({'patient_name':'DOE, JANE','patient_dob':'02/17/1985','insured_id_number':'ABC123456','total_charge':'125.00'})
    assert disposition=='HITL'
    assert blockers

def test_placeholder_presence_never_mints_stp():
    disposition,_=promote_unstructured_fields({'patient_name':'PATIENT NAME','patient_dob':'99/99/9999','insured_id_number':'000000000','total_charge':'0.00'})
    assert disposition!='TRUE_STP'
