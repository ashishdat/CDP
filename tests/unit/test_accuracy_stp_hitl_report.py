import csv
import json
from scripts.summarize_accuracy_stp_hitl import build_report


def setup_run(tmp_path):
    (tmp_path/'launch.json').write_text(json.dumps({'documents': 5}))
    rows = [
        {'document':'a','claim_id':'a','finished':True,'completed':True,'true_stp':True,'disposition':'TRUE_STP'},
        {'document':'b','claim_id':'b','finished':True,'completed':True,'true_stp':False,'disposition':'HITL'},
        {'document':'c','claim_id':'c','finished':True,'completed':False,'true_stp':False,'disposition':'REGISTRATION_FAILED'},
        {'document':'d','claim_id':'d','finished':True,'completed':False,'true_stp':False,'disposition':'STAGE_FAILURE'},
    ]
    (tmp_path/'results.jsonl').write_text('\n'.join(json.dumps(r) for r in rows)+'\n{"unfinished":')
    return tmp_path


def test_outcomes_partition_processed_and_pending_is_excluded(tmp_path):
    result=build_report(setup_run(tmp_path))
    assert result['processed']==4 and result['pending']==1
    assert result['stp']['rate_of_processed']==0.25
    assert result['hitl']['total']==2
    assert result['technical_failures']['count']==1
    assert result['accuracy']['status']=='unavailable'


def test_reviewed_labels_and_missing_empty_predictions(tmp_path):
    root=setup_run(tmp_path)
    final=root/'claims/a/final'
    final.mkdir(parents=True)
    (final/'FinalClaim.json').write_text(json.dumps({'decision':{'field_decisions':[
        {'field_name':'patient_name','selected_value':'JANE DOE','disposition':'AUTO_ACCEPTED'}]}}))
    labels=root/'labels.csv'
    with labels.open('w',newline='') as f:
        w=csv.writer(f)
        w.writerow(['document','field_name','expected_value','reviewed','reviewer'])
        w.writerows([['a','patient_name','JANE DOE','true','tester'],
                     ['c','patient_name','','true','tester'],
                     ['b','patient_name','ignored','false','']])
    result=build_report(root,labels)['accuracy']
    assert result['reviewed_fields']==2
    assert result['field_accuracy']==0.5
    assert result['auto_accepted_field_accuracy']==1
