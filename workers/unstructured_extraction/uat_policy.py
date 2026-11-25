"""UAT document type nomination and evidence checks from versioned local rules."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / 'config/uat_document_acceptance.yaml'


def nominate_type(filename, manifest_type, config):
    # Exact tokens prevent PAN from matching unrelated filenames. A filename
    # remains only a nomination; content verification is performed separately.
    stem = Path(filename).stem.upper()
    for kind, spec in config['types'].items():
        for marker in spec['markers']:
            if re.search(r'(?:^|_)' + re.escape(marker) + r'(?:_|$)', stem):
                return kind
    kind = str(manifest_type).upper()
    kind = config.get('manifest_aliases', {}).get(kind, kind)
    return kind if kind in config['types'] else 'OTHER'


def content_matches(kind, text, config):
    anchors = config['types'][kind]['content_anchors']
    normalized = ' '.join(text.lower().split())
    return bool(anchors) and any(anchor in normalized for anchor in anchors)


def load_policy():
    return yaml.safe_load(POLICY.read_text(encoding='utf-8'))
