"""Explicit, source-specific operator geometry; never a global template override."""
import hashlib,json,math
from pathlib import Path

def frame_hash(geometry):
    keys=('page_number','template_id','template_version','coordinate_frame','source_to_geometry_transform')
    return hashlib.sha256(json.dumps({k:geometry.get(k) for k in keys},sort_keys=True).encode()).hexdigest()

def load_approved_geometry(path,expected_hash,source_sha256,geometry,image_size):
    payload=Path(path).read_bytes()
    if not expected_hash or hashlib.sha256(payload).hexdigest()!=expected_hash:
        raise ValueError('Approved geometry manifest integrity mismatch')
    manifest=json.loads(payload)
    if manifest.get('schema_version')!='approved-source-geometry-v1' or manifest.get('operator_validated') is not True:
        raise ValueError('Operator-validated source geometry required')
    matches={}
    for entry in manifest['entries']:
        if entry['source_sha256']!=source_sha256 or entry['page_number']!=geometry['page_number']:
            continue
        if entry['frame_sha256']!=frame_hash(geometry):
            raise ValueError('Approved geometry frame changed; revalidation required')
        box=entry['bbox']
        if len(box)!=4 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in box):
            raise ValueError('Invalid approved geometry coordinates')
        if not(0<=box[0]<box[2]<=image_size[0] and 0<=box[1]<box[3]<=image_size[1]):
            raise ValueError('Approved geometry outside source frame')
        if entry['field'] in matches:raise ValueError('Ambiguous approved field geometry')
        matches[entry['field']]={**entry,'runtime_binding_verified':True}
    return matches

def acquire_approved_geometry(rows,image,entries,recognize):
    updated=[]
    for row in rows:
        entry=entries.get(row['field'])
        if not entry:
            updated.append(row);continue
        current={**row,'candidates':list(row.get('candidates') or []),'attempts':list(row.get('attempts') or [])}
        candidates,attempts,reason=recognize(row['field'],tuple(entry['bbox']))
        for candidate in candidates:
            candidate={**candidate,'source_geometry_validation_id':entry['validation_id']}
            current['candidates'].append(candidate)
        current['attempts'].extend(attempts)
        current['acquisition_executed']=True
        current['status']='CANDIDATES_OBSERVED' if current['candidates'] else 'NO_VALUE'
        current['approved_geometry']={**entry,'acquisition_reason':reason,'candidate_count':len(candidates),'acceptance_authority':'EXISTING_FIELD_AND_CLAIM_GATES'}
        if entry.get('runtime_binding_verified'):
            current['local_alignment']={'accepted':True,'reason':'OPERATOR_SOURCE_FIELD_GEOMETRY_VERIFIED',
                'scope':'EXACT_SOURCE_PAGE_FIELD_FRAME','validation_id':entry['validation_id'],
                'observed_bbox':entry['bbox'],'original_alignment':row.get('local_alignment')}
        # This is additional observation. Keep original geometry and all rivals.
        if row['field']=='patient_dob':
            from packages.extraction_recovery.dob_confirmation import dob_component_conflicts
            current['dob_component_conflicts']=dob_component_conflicts(current['candidates'],current['attempts'])
        updated.append(current)
    return updated
