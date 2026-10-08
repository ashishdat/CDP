"""Bounded recovery proposal from measured ink; no reading or acceptance authority."""
import math

def measured_year_recovery(cell,components,legacy_year_right=868):
    x0,y0,x1,y1=cell
    if not(x0<740<795<x1):return None
    minimum_height=max(16,math.ceil((y1-y0)*.36))
    glyphs=[]
    for component in components:
        b=component.get('box') or {}
        if any(k not in b for k in ('x0','y0','x1','y1')):continue
        values=[b[k] for k in ('x0','y0','x1','y1')]
        if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):continue
        a,c,d,e=values;width=d-a;height=e-c
        if not(x0<=a<d<=x1 and y0<=c<e<=y1):continue
        if 3<=width<=35 and minimum_height<=height<=(y1-y0)*.9 and component.get('area',0)>=20:
            glyphs.append(tuple(values))
    mm=[b for b in glyphs if (b[0]+b[2])/2<740]
    dd=[b for b in glyphs if 740<=(b[0]+b[2])/2<795]
    if len(mm)!=2 or len(dd)!=2:return None
    anchors=mm+dd
    if max(b[3] for b in anchors)-min(b[3] for b in anchors)>3:return None
    baseline=sum(b[3] for b in anchors)/4
    year=[b for b in glyphs if (b[0]+b[2])/2>=795 and abs(b[3]-baseline)<=3]
    if not 2<=len(year)<=4:return None
    ink_right=max(b[2] for b in year)
    if ink_right<=legacy_year_right or not any(b[0]<legacy_year_right<b[2] for b in year):return None
    top=max(y0,min(b[1] for b in anchors+year)-2)
    bottom=min(y1,max(b[3] for b in anchors+year)+2)
    right=min(x1,ink_right+3)
    return {'qualified':True,'reason':'MEASURED_YEAR_INK_EXCEEDS_LEGACY_CROP',
        'year_bbox':[798,top,right,bottom],'year_ink_boxes':[list(b) for b in year],
        'anchor_ink_boxes':[list(b) for b in anchors],'legacy_year_right':legacy_year_right,
        'safe_cell':list(cell),'acceptance_authority':'NONE'}
