"""Score independent field labels; refuse unreviewed or mismatched rows."""
import argparse
import csv
import io
import json
from pathlib import Path

from workers.unstructured_extraction.extraction_acceptance import normalized


def score(path):
    seen = set()
    correct = total = 0
    for row in csv.DictReader(io.StringIO(Path(path).read_text(encoding='utf-8'))):
        if row['reviewed'].lower() != 'true' or not row['reviewer'].strip():
            raise ValueError('Every label must have independent review and a named reviewer')
        key = (row['document_id'], row['field'])
        if key in seen:
            raise ValueError('Duplicate field label')
        seen.add(key)
        doc = json.loads(Path(row['evidence_file']).read_text(encoding='utf-8'))
        if doc['id'] != row['document_id'] or doc['sha256'] != row['sha256']:
            raise ValueError('Label/source identity mismatch')
        actual = doc['decision']['extracted_fields'].get(row['field'], {}).get('value', '')
        correct += normalized(row['field'], actual) == normalized(row['field'], row['expected_value'])
        total += 1
    if not total:
        raise ValueError('No independently reviewed labels')
    return {'reviewed_fields': total, 'correct_fields': correct, 'field_accuracy': correct / total,
            'correct_case_stp_rate': None, 'independent_case_validation_required': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('labels', type=Path)
    print(json.dumps(score(parser.parse_args().labels), indent=2))
