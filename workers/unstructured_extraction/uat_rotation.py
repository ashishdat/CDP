"""Quarter-turn normalization with recorded coordinate/crop transformations."""
import copy


def rotation_angle(di):
    pages=(di.get('payload',{}).get('analyzeResult') or {}).get('pages',[])
    angle=pages[0].get('angle',0) if pages else 0
    snapped=round(angle/90)*90
    return snapped if abs(angle-snapped)<=18 else 0


def point(x,y,width,height,angle):
    angle=angle%360
    if angle==90:return y,width-x
    if angle==180:return width-x,height-y
    if angle==270:return height-y,x
    return x,y


def transform_di(di,asset,angle):
    result=copy.deepcopy(di)
    for page in (result.get('payload',{}).get('analyzeResult') or {}).get('pages',[]):
        w,h=asset['width'],asset['height'];sx=w/page['width'];sy=h/page['height']
        for collection in ['words','lines','selectionMarks']:
            for item in page.get(collection,[]):
                poly=item.get('polygon',[]);item['polygon']=[v for x,y in zip(poly[::2],poly[1::2],strict=True)
                    for v in point(x*sx,y*sy,w,h,angle)]
        page.update(width=h if angle%180 else w,height=w if angle%180 else h,unit='pixel',angle=0)
    result['preprocessing']={'rotation_counterclockwise':angle,'source_asset':asset,
                             'provider_payload_reused':True,'new_cloud_call':False}
    return result


def crop_fraction(box,width,height,angle):
    corners=[point(x*width,y*height,width,height,angle) for x,y in
             [(box[0],box[1]),(box[2],box[1]),(box[2],box[3]),(box[0],box[3])]]
    nw,nh=(height,width) if angle%180 else (width,height)
    return [max(0,min(p[0] for p in corners)/nw),max(0,min(p[1] for p in corners)/nh),
            min(1,max(p[0] for p in corners)/nw),min(1,max(p[1] for p in corners)/nh)]
