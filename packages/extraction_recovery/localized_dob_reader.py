"""Blind same-reader component acquisition using qualified observed positions."""
import re
from packages.extraction_recovery.dob_azure_di_residual import _shape_dob_text

def read_localized_dob(image, record, canonical, reader):
    if record.get('source_sha256'):
        from packages.extraction_recovery.dob_recovery_contract import qualify_value_row
        if not qualify_value_row(record,canonical)['qualified']:
            return None, []
    elif not (record.get('qualification') or {}).get('qualified'):
        return None, []
    words = [w for w in (record.get('di') or {}).get('words', []) if re.fullmatch(r'[0-9]{2}|[0-9]{4}',str(w.get('content') or ''))]
    if len(words) != 3 or record.get('prior_hints_supplied'):
        return None, []
    origin = record['context_bbox'][:2]
    boxes = []
    for word in words:
        p = word.get('polygon') or []
        if len(p) != 8:
            return None, []
        box = [int(min(p[::2])+origin[0]),int(min(p[1::2])+origin[1]),int(max(p[::2])+origin[0]),int(max(p[1::2])+origin[1])]
        if not (canonical[0] <= box[0] < box[2] <= canonical[2] and canonical[1] <= box[1] < box[3] <= canonical[3]):
            return None, []
        boxes.append(box)
    boxes.sort(key=lambda b:b[0])
    if any(a[2] > b[0] for a,b in zip(boxes,boxes[1:])) or max(b[1] for b in boxes)>=min(b[3] for b in boxes):
        return None, []
    parts, scores, attempts = {}, [], []
    for label,box in zip(('MM','DD','YY'),boxes):
        padded=(max(canonical[0],box[0]-2),max(canonical[1],box[1]-2),min(canonical[2],box[2]+2),min(canonical[3],box[3]+2))
        crop=image.crop(padded)
        up=crop.resize((crop.width*3,crop.height*3))
        try:
            identity={key:record.get(key) for key in ('source_sha256','page_number','frame_sha256')}
            is_new_observation=True
            observation_id=None
            if all(identity.values()):
                import hashlib
                from packages.extraction_recovery.dob_recovery_contract import ObservationKey,ObservationLedger
                ledger=getattr(image,'_dob_literal_observation_ledger',None)
                if ledger is None:
                    ledger=ObservationLedger();image._dob_literal_observation_ledger=ledger
                pixel_hash=hashlib.sha256(str((up.mode,up.size)).encode()+up.tobytes()).hexdigest()
                key=ObservationKey(**identity,field='patient_dob:'+label,bbox=tuple(padded),pixels_sha256=pixel_hash,reader='tesseract:'+str(id(reader)),profile='localized-dob-v1/psm7')
                observed,is_new_observation=ledger.observe(key,lambda:reader(up,'--psm 7'))
                text,score=observed.text,observed.raw_confidence;observation_id=observed.observation_id
            else:
                text,score=reader(up,'--psm 7')
        except Exception as exc:
            attempts.append({'engine':'tesseract','reason':'LOCALIZED_DOB_READER_ERROR','error_type':type(exc).__name__,'input_bbox':list(padded)})
            return None, attempts
        finally:
            crop.close();up.close()
        text=str(text or '').strip()
        attempts.append({'engine':'tesseract','reason':'LOCALIZED_DOB_COMPONENT_OBSERVED','dob_cell':label,'input_bbox':list(padded),
                         'observation':{'text':text,'raw_confidence':score},'prior_hints_supplied':False,'position_provider':'azure_document_intelligence_read','observation_id':observation_id,'new_reader_observation':is_new_observation})
        pattern=r'[0-9]{2}' if label!='YY' else r'(?:[0-9]{2}|[0-9]{4})'
        if not re.fullmatch(pattern,text) or not isinstance(score,(int,float)) or not 0 < score <= 1:
            return None, attempts
        parts[label]=text;scores.append(score)
    value,valid=_shape_dob_text('patient_dob',' '.join(parts.values()),allow_ordered_components=True)
    if not valid:
        return None,attempts
    attempts.append({'engine':'tesseract','reason':'LOCALIZED_DOB_COMPLETE','observation':{'parts':parts},'prior_hints_supplied':False})
    return {'value':value,'raw_value':' '.join(parts.values()),'engine':'tesseract','raw_confidence':min(scores),'calibrated_confidence':None,
            'preprocessing_variant':'qualified_word_positions_blind_tesseract','preprocessing_version':'localized-dob-v1','model_name':'tesseract',
            'model_version':'installed','prior_hints_supplied':False},attempts
