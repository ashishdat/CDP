"""UB-04 registered crops: observed candidates, local printed-landmark gates.

No CMS Box 24/28 heuristics or service-line sum promotion. ClaimDecisionService
remains the acceptance owner. Missing local evidence yields empty candidates.
"""
from pathlib import Path
import cv2
import numpy as np
import yaml
import math
from PIL import Image
from packages.domain.ub04 import UB04ServiceLine

ROOT = Path(__file__).resolve().parents[2]
CRITICAL = {"patient_name", "patient_dob", "insured_id_number", "total_charge"}


def validate_landmark(image, reference, box, *, search_radius=12, minimum_score=.75, maximum_residual=3):
    """Locate a static printed patch near its expected rectified position."""
    x0,y0,x1,y1 = map(int, box)
    source = np.asarray(image.convert("L"))
    blank = np.asarray(reference.convert("L"))
    if source.shape != blank.shape or not (0 <= x0 < x1 <= blank.shape[1] and 0 <= y0 < y1 <= blank.shape[0]):
        return {"accepted":False,"reason":"LANDMARK_BOUNDS_INVALID"}
    if x0 < search_radius or y0 < search_radius or x1+search_radius > source.shape[1] or y1+search_radius > source.shape[0]:
        return {"accepted":False,"reason":"LANDMARK_SEARCH_CLIPPED"}
    # Captions contain fixed ink, not patient data; retain line/text contrast.
    target = (blank[y0:y1,x0:x1] < 180).astype(np.float32)
    if target.sum() < 30:
        return {"accepted":False,"reason":"LANDMARK_REFERENCE_EMPTY"}
    search = (source[y0-search_radius:y1+search_radius,x0-search_radius:x1+search_radius] < 180).astype(np.float32)
    scores = cv2.matchTemplate(search, target, cv2.TM_CCORR_NORMED)
    _, score, _, location = cv2.minMaxLoc(scores)
    dx,dy = location[0]-search_radius,location[1]-search_radius
    accepted = bool(np.isfinite(score) and score >= minimum_score and max(abs(dx),abs(dy)) <= maximum_residual)
    return {"accepted":accepted,"score":float(score),"residual_px":[dx,dy],"expected_bbox":list(box),
            "reason":"LOCAL_PRINTED_LANDMARK_VERIFIED" if accepted else "LOCAL_ALIGNMENT_REQUIRES_REVIEW"}



def validate_cell_frame(image, reference, box, *, maximum_residual=3, radius=12):
    """Check all four printed cell edges, independently of caption font."""
    x0,y0,x1,y1=map(int,box)
    source=np.asarray(image.convert("L")); blank=np.asarray(reference.convert("L"))
    if source.shape != blank.shape or not (radius <= x0 < x1 < source.shape[1]-radius and radius <= y0 < y1 < source.shape[0]-radius):
        return {"accepted":False,"reason":"CELL_FRAME_BOUNDS_INVALID"}
    residuals=[]
    for axis,expected,start,end in [(0,y0,x0,x1),(0,y1,x0,x1),(1,x0,y0,y1),(1,x1,y0,y1)]:
        def locate(pixels):
            ink=(pixels < 180).astype(np.uint8)
            if axis == 0:
                strip=ink[expected-radius:expected+radius+1,start+3:end-3]
                scores=strip.mean(axis=1)
            else:
                strip=ink[start+3:end-3,expected-radius:expected+radius+1]
                scores=strip.mean(axis=0)
            if len(scores)==0 or scores.max()<.6:return None
            # Contiguous ruling can be several pixels thick. Use its center.
            indices=np.flatnonzero(scores >= max(.6,float(scores.max())*.9))
            closest=indices[np.argmin(abs(indices-radius))]
            connected=indices[abs(indices-closest)<=2]
            return float(connected.mean()-radius)
        ref=locate(blank); observed=locate(source)
        if ref is None or observed is None:
            return {"accepted":False,"reason":"CELL_FRAME_EDGE_MISSING"}
        residuals.append(observed-ref)
    accepted=max(abs(v) for v in residuals)<=maximum_residual
    return {"accepted":accepted,"edge_residuals_px":residuals,
        "reason":"LOCAL_CELL_FRAME_VERIFIED" if accepted else "LOCAL_CELL_FRAME_RESIDUAL_EXCEEDED"}


def extract_registered_ub04(image, geometry, template, reference, recognize, emit=lambda rows:None):
    """Return standard OCR rows plus a distinct UB-04 service-line schema."""
    cfg = yaml.safe_load((ROOT/"config/ub04_registered_v2.yaml").read_text(encoding="utf-8"))
    valid_binding = (template.template_id == "ub04" and template.version == cfg["template_version"]
                     and geometry.get("status") == "SUCCESS" and geometry.get("coordinate_frame") == "rectified_template_pixels")
    checks = {}
    if valid_binding and reference is not None:
        for name,box in cfg["landmarks"].items():
            checks[name] = validate_landmark(image, reference, box,
                search_radius=cfg["search_radius_px"],minimum_score=cfg["minimum_score"],maximum_residual=cfg["maximum_residual_px"])
        unchanged_print_support=sum(bool(check.get('accepted')) for check in checks.values()) >= 2
        for name,box in cfg.get("frame_landmarks",{}).items():
            frame = validate_cell_frame(image,reference,box,maximum_residual=cfg["maximum_frame_edge_residual_px"])
            caption = checks.get(name,{"accepted":False})
            checks[name] = {**caption,"printed_caption":caption,"cell_frame":frame,
                "accepted":bool(frame.get('accepted') or (caption.get('accepted') and not frame.get('edge_residuals_px'))),
                "reason":"LOCAL_ALIGNMENT_VERIFIED" if frame.get('accepted') or (caption.get('accepted') and not frame.get('edge_residuals_px')) else "LOCAL_ALIGNMENT_REQUIRES_REVIEW"}
            residuals = frame.get("edge_residuals_px")
            # Recover translation only when all four static edges agree. A
            # changed cell width/height or a larger offset needs a layout review.
            if not checks[name]["accepted"] and name != "service_lines" and residuals:
                top,bottom,left,right=residuals
                dx,dy=round((left+right)/2),round((top+bottom)/2)
                coherent=max(abs(left-right),abs(top-bottom)) <= 1.5
                if coherent and max(abs(dx),abs(dy)) <= 6:
                    shifted=Image.fromarray(cv2.warpAffine(np.asarray(image.convert("L")),
                        np.array([[1.,0.,-dx],[0.,1.,-dy]]),image.size,borderValue=255))
                    recovered=validate_cell_frame(shifted,reference,box,
                        maximum_residual=cfg["maximum_frame_edge_residual_px"])
                    shifted.close()
                    if recovered.get("accepted"):
                        checks[name]={**checks[name],"accepted":True,
                            "reason":"LOCAL_CELL_TRANSLATION_VERIFIED",
                            "crop_translation_px":[dx,dy],"corrected_cell_frame":recovered}
            # Small renderer stretch cannot be repaired by translation alone.
            # Measure only long printed walls, bound the deformation, and
            # recheck the corrected frame at the original residual threshold.
            if unchanged_print_support and not checks[name]['accepted'] and name != 'service_lines' and residuals:
                top,bottom,left,right=residuals
                x0,y0,x1,y1=box
                sx=((x1+right)-(x0+left))/(x1-x0)
                sy=((y1+bottom)-(y0+top))/(y1-y0)
                if max(map(abs,residuals)) <= 12 and .9 <= sx <= 1.1 and .9 <= sy <= 1.1:
                    tx=x0+left-sx*x0;ty=y0+top-sy*y0
                    corrected=Image.fromarray(cv2.warpAffine(np.asarray(image.convert('L')),
                        np.array([[1/sx,0,-tx/sx],[0,1/sy,-ty/sy]]),image.size,borderValue=255))
                    verified=validate_cell_frame(corrected,reference,box,
                        maximum_residual=cfg['maximum_frame_edge_residual_px'])
                    corrected.close()
                    if verified.get('accepted'):
                        checks[name]={**checks[name],'accepted':True,'reason':'LOCAL_CELL_AFFINE_VERIFIED',
                            'crop_affine':[sx,sy,tx,ty],'corrected_cell_frame':verified,
                            'observed_cell_bbox':[x0+left,y0+top,x1+right,y1+bottom]}
    rows=[]
    for field in geometry.get("fields",[]):
        name=field["field"]; roi=(field.get("result") or {}).get("aligned_roi") or {}
        bbox=[roi.get(k) for k in ("x0","y0","x1","y1")]
        region=template.field_region(name)
        expected=[getattr(region,k) for k in ("x0","y0","x1","y1")] if region else None
        local = checks.get(name,{"accepted":False,"reason":"NO_QUALIFIED_LOCAL_LANDMARK"})
        if name == "total_charge":
            local = {**local,"accepted":bool(local.get("accepted") and checks.get("total_charge_totals",{}).get("accepted")),"totals_landmark":checks.get("total_charge_totals")}
        # Noncritical fields are preserved as unassessed stubs until landmarks are qualified.
        allowed = valid_binding and bbox == expected and local.get("accepted")
        if bbox != expected or not valid_binding:
            local={**local,"accepted":False,"reason":"UB04_FIELD_GEOMETRY_BINDING_INVALID"}
        dx,dy=local.get("crop_translation_px",[0,0])
        observed_bbox=[bbox[0]+dx,bbox[1]+dy,bbox[2]+dx,bbox[3]+dy] if allowed else bbox
        if allowed and local.get('crop_affine'):
            sx,sy,tx,ty=local['crop_affine']
            observed_bbox=[math.floor(sx*bbox[0]+tx),math.floor(sy*bbox[1]+ty),
                           math.ceil(sx*bbox[2]+tx),math.ceil(sy*bbox[3]+ty)]
        allowed = allowed and 0 <= observed_bbox[0] < observed_bbox[2] <= image.width and 0 <= observed_bbox[1] < observed_bbox[3] <= image.height
        if local.get("accepted") and not allowed:
            local={**local,"accepted":False,"reason":"UB04_RECOVERED_CROP_OUT_OF_BOUNDS"}
        candidates,attempts,reason = recognize(name,tuple(observed_bbox),region.field_type) if allowed else ([],[],"LOCAL_ALIGNMENT_REQUIRES_REVIEW")
        rows.append({"field":name,"canonical_region":bbox,"ocr_region":observed_bbox,"candidates":candidates,"attempts":attempts,
                     "router_reason":reason,"status":"ACQUISITION_BLOCKED" if not allowed else ("CANDIDATES_OBSERVED" if candidates else "NO_VALUE"),
                     "acquisition_executed":bool(allowed),"blankness_established":False,
                     "local_alignment":local,"cascade":{"strategy_id":"ub04-registered-v2","accepted":False,"accept_reason":"GOVERNED_DECISION_REQUIRED","steps":[]}})
        emit(rows)
    lines=[]; table=template.service_line_region; activity=[]
    if valid_binding and table and checks.get("service_lines",{}).get("accepted"):
        # Exact fractional partition of 22 rows: rounded fixed height would drift.
        source_ink = np.asarray(image.convert("L")) < 180
        reference_ink = np.asarray(reference.convert("L")) < 180
        radius = int(cfg["maximum_frame_edge_residual_px"])
        printed_neighborhood = cv2.dilate(reference_ink.astype(np.uint8),
            np.ones((2*radius+1, 2*radius+1), np.uint8)) > 0
        for index in range(table.max_rows):
            y0=round(table.table_y0+(table.table_y1-table.table_y0)*index/table.max_rows)
            y1=round(table.table_y0+(table.table_y1-table.table_y0)*(index+1)/table.max_rows)
            row_box=[table.table_x0,y0,table.table_x1,y1]
            # Blank rows are explicitly examined; never stop on an internal gap.
            bounds=(slice(y0+3,y1-3),slice(table.table_x0+3,table.table_x1-3))
            distinct_ink=int(np.count_nonzero(source_ink[bounds] & ~printed_neighborhood[bounds]))
            activity.append({"row_number":index+1,"distinct_ink_pixels":distinct_ink,
                "status":"DISTINCT_INK_OBSERVED" if distinct_ink >= 20 else "NO_DISTINCT_INK_OUTSIDE_PRINTED_NEIGHBORHOOD"})
            # Differences within the verified local residual are printed-form
            # noise, not evidence of a new service line. Preserve diagnostics;
            # this activity check cannot establish an authoritative blank row.
            if distinct_ink < 20:
                continue
            cells={}
            for column in table.columns:
                bbox=(column.x0,y0+3,column.x1,y1-3)
                candidates,attempts,reason=recognize(column.field_name,bbox,column.field_type)
                cells[column.field_name]={"canonical_region":list(bbox),"candidates":candidates,"attempts":attempts,"router_reason":reason}
            lines.append(UB04ServiceLine(row_number=index+1,canonical_region=tuple(row_box),cells=cells).model_dump(mode="json"))
    return rows,lines,{"version":"ub04-local-alignment-v1","binding_qualified":valid_binding,"landmarks":checks,
                       "critical_fields_blocked":[r["field"] for r in rows if r["field"] in (CRITICAL | set(template.required_fields)) and not r["local_alignment"].get("accepted")],
                       "service_rows_examined":len(activity),"service_row_activity":activity}
