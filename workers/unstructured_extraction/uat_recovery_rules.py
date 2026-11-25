"""Source-bound masking, visual document evidence and case-name recovery."""
import importlib.util
import re
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np


def name_key(value):
    value = re.sub(r'^(?:mrs|mr|ms|dr)(?:\.\s*|\s+)', '', value, flags=re.IGNORECASE)
    return ' '.join(re.findall(r'[a-z]+', value.casefold()))


def name_similarity(left, right):
    a, b = name_key(left), name_key(right)
    if not a or not b:
        return 0
    at,bt=a.split(),b.split()
    # Reordered initials are equivalent only when every initial and the whole
    # non-initial name agree. Joining SIVA KUMAR preserves the source letters.
    ai, bi = sorted(t for t in at if len(t) <= 2), sorted(t for t in bt if len(t) <= 2)
    af, bf = ''.join(t for t in at if len(t) > 2), ''.join(t for t in bt if len(t) > 2)
    if ai and ai == bi and af == bf and len(af) >= 4:
        return .96
    # Initials are supported only alongside a fully matching surname.
    if len(at)>=2 and len(bt)>=2 and at[-1]==bt[-1]:
        if at[0]==bt[0] and (len(at)==2 or len(bt)==2):
            return .96  # A middle name may be omitted, never contradicted.
        if len(at)==len(bt) and all(x==y or (min(len(x),len(y))<=2 and (x.startswith(y) or y.startswith(x)))
                                    for x,y in zip(at,bt,strict=True)):
            return .96
    # A shared first name alone does not establish a source-name match.
    return max(SequenceMatcher(None, a, b).ratio(),
               SequenceMatcher(None, ' '.join(sorted(a.split())), ' '.join(sorted(b.split()))).ratio())


def case_name_candidates(pages, known_names):
    candidates = []
    for page in pages:
        for line in page.lines:
            if re.search(r'doctor|physician|consultant|referred|father|mother|examiner', line.text, re.IGNORECASE):
                continue
            tokens = line.tokens
            for known in known_names:
                length = len(name_key(known).split())
                for start in range(len(tokens)):
                    for size in {max(1, length - 1), length, length + 1}:
                        span = tokens[start:start + size]
                        if not span:
                            continue
                        value = ' '.join(token.text for token in span).strip(' :')
                        similarity = name_similarity(value, known)
                        if similarity < .90:
                            continue
                        candidates.append({'value': value, 'raw_confidence': min(t.confidence or 0 for t in span),
                            'page_number': span[0].page_number, 'field_association': 'CASE_NAME_SOURCE_MATCH',
                            'case_name_similarity': similarity, 'case_known_name': known,
                            'evidence_reference': f'page:{span[0].page_number}:case_name_source_match',
                            'bounding_box': {'x0': min(t.bbox.x0 for t in span), 'y0': min(t.bbox.y0 for t in span),
                                             'x1': max(t.bbox.x1 for t in span), 'y1': max(t.bbox.y1 for t in span)}})
    return candidates


def visual_evidence(assets, pages):
    result = {'version': 'local-visual-v4-2', 'portraits': [], 'waveforms': []}
    if not hasattr(cv2,'CascadeClassifier'):
        raise RuntimeError('Local portrait detection requires the .venv-ocr OpenCV runtime')
    cascade_path=Path(cv2.data.haarcascades)/'haarcascade_frontalface_default.xml'
    if not cascade_path.exists():
        spec=importlib.util.find_spec('skimage')
        cascade_path=Path(spec.origin).parent/'data/lbpcascade_frontalface_opencv.xml' if spec else cascade_path
    if not cascade_path.exists():
        raise RuntimeError('Local face cascade model is not installed')
    cascade = cv2.CascadeClassifier(str(cascade_path))
    fallback=None
    if cascade.empty():
        from skimage.feature import Cascade
        fallback=Cascade(str(cascade_path))
    for asset, page in zip(assets, pages, strict=True):
        path = Path(asset['path'])
        if not path.exists():
            continue
        im = cv2.imread(str(path))
        if im is None:
            continue
        h, w = im.shape[:2]
        scale = min(1, 1200 / max(w, h))
        gray = cv2.cvtColor(cv2.resize(im, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY)
        no_text=not any((token.confidence or 0)>=.80 and re.search(r'\w{3}',token.text)
            for line in page.lines for token in line.tokens)
        if not no_text or not .5 <= w/h <= 1.6:
            faces=[]
        elif fallback:
            boxes=fallback.detect_multi_scale(gray,scale_factor=1.2,step_ratio=1,
                min_size=(30,30),max_size=gray.shape,min_neighbor_number=5)
            faces=[(b['c'],b['r'],b['width'],b['height']) for b in boxes]
        else:
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        if len(faces) == 1 and .5 <= w / h <= 1.6:
            x, y, fw, fh = faces[0]
            if fw * fh / gray.size >= .08:
                result['portraits'].append({'page': asset['page'], 'basis': 'LOCAL_FACE_DETECTION',
                    'bounding_box': [int(v / scale) for v in (x, y, x + fw, y + fh)]})
        # A grid alone is not a waveform: require multiple visible ECG leads too.
        text = ' '.join(line.text for line in page.lines)
        leads = set(re.findall(r'\b(?:aVR|aVL|aVF|V[1-6])\b', text, re.IGNORECASE))
        edges = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 12)
        horizontal = cv2.morphologyEx(edges, cv2.MORPH_OPEN, np.ones((1, 25), np.uint8))
        vertical = cv2.morphologyEx(edges, cv2.MORPH_OPEN, np.ones((25, 1), np.uint8))
        if len(leads) >= 3 and np.mean(horizontal > 0) > .003 and np.mean(vertical > 0) > .003:
            result['waveforms'].append({'page': asset['page'], 'basis': 'GRID_AND_ECG_LEAD_MARKERS',
                                         'lead_markers': sorted(leads)})
    return result


def masked_candidates(assets, pages):
    """Accept explicit masks or a solid redaction next to a four-digit suffix.

    Match must be repeated independently on the source pages or against another
    case document. Merely finding four digits never constitutes a masked ID.
    """
    found = []
    for asset, page in zip(assets, pages, strict=True):
        text = ' '.join(line.text for line in page.lines)
        if not re.search(r'aadhaa?r|unique identification|government of india', text, re.IGNORECASE):
            continue
        for line_index, line in enumerate(page.lines):
            for match in re.finditer(r'(?:[xX*#\u2022\u25cf]\s*){8}\d{4}', line.text):
                found.append({'value': 'XXXXXXXX' + match.group()[-4:], 'page_number': asset['page'],
                    'raw_confidence': min((t.confidence or 0 for t in line.tokens), default=0),
                    'field_association': 'MASKED_ID_SOURCE_PATTERN', 'mask_basis': 'EXPLICIT_EIGHT_MASK_CHARACTERS',
                    'evidence_reference': f"page:{asset['page']}:masked_aadhaar:line:{line_index}", 'suffix': match.group()[-4:]})
        im = cv2.imread(str(asset['path']))
        if im is None:
            continue
        for line in page.lines:
            for token in line.tokens:
                if not re.fullmatch(r'\d{4}', token.text):
                    continue
                b = token.bbox
                th, tw = max(1, b.y1 - b.y0), max(1, b.x1 - b.x0)
                # Solid black/pink/white rectangles must occupy the expected
                # leading-eight-digit area directly beside the suffix.
                x0, x1 = max(0, int(b.x0 - 3.5 * tw)), int(b.x0)
                y0, y1 = max(0, int(b.y0 - .25 * th)), min(im.shape[0], int(b.y1 + .25 * th))
                crop = im[y0:y1, x0:x1]
                if not crop.size:
                    continue
                hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
                pink = ((hsv[:, :, 0] > 135) & (hsv[:, :, 0] < 179) & (hsv[:, :, 1] > 60)).astype('uint8') * 255
                dark = (cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) < 40).astype('uint8') * 255
                for mask in [pink, dark]:
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for contour in contours:
                        x, y, w, h = cv2.boundingRect(contour)
                        if (1.3 * tw <= w <= 3.5 * tw and .65 * th <= h <= 2 * th
                                and x1 - (x0 + x + w) <= .4 * tw
                                and cv2.contourArea(contour) / (w * h) >= .92):
                            found.append({'value': 'XXXXXXXX' + token.text, 'suffix': token.text,
                                'page_number': asset['page'], 'raw_confidence': token.confidence or 0,
                                'field_association': 'MASKED_ID_SOURCE_PATTERN',
                                'mask_basis': 'SOLID_REDACTION_ADJACENT_TO_SUFFIX',
                                'bounding_box': {'x0': x0 + x, 'y0': y0 + y, 'x1': b.x1, 'y1': max(y0 + y + h, b.y1)},
                                'evidence_reference': f"page:{asset['page']}:masked_aadhaar:{int(b.x0)}:{int(b.y0)}"})
    return found


def confirm_mask_matches(candidates, case_suffixes=()):
    for item in candidates:
        matches = [other for other in candidates if other['suffix'] == item['suffix']
                   and other['evidence_reference'] != item['evidence_reference']]
        item['last4_match_verified'] = bool(matches or item['suffix'] in case_suffixes)
        item['last4_match_basis'] = 'REPEATED_SOURCE_NUMBER' if matches else 'OTHER_CASE_DOCUMENT' if item['suffix'] in case_suffixes else None
    return candidates
