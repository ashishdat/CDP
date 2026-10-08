"""Caption-aware literal DOB component acquisition; one real reader, no authority."""
import re
from packages.extraction_recovery.dob_azure_di_residual import _shape_dob_text
from packages.ocr.observed_confidence import observed_confidence


def read_literal_components(image,cells,*,extractor,preprocess):
    parts={};scores={};attempts=[];single_month=False
    for label,box in cells.items():
        crop=preprocess(image.crop(box))
        try:lines=extractor.extract(crop)
        except Exception as exc:
            crop.close()
            return None,[{'engine':'tesseract','reason':'DOB_LITERAL_READER_ERROR:'+type(exc).__name__,'reader_failed':True}]
        choices=[]
        numeric_words=[line for line in lines if re.fullmatch(r'[0-9]{1,4}',line.text.strip())]
        captions=[line for line in lines if line.text.strip().upper()==label]
        for line in lines:
            if len(numeric_words)!=1:break  # Never drop or merge another observed number.
            text=line.text.strip()
            if not (3 < line.x0 < line.x1 < crop.width-3 and 3 < line.y0 < line.y1 < crop.height-3):continue
            if not re.fullmatch(r'[0-9]{1,4}',text):continue
            if label=='MM':
                if not 1<=int(text)<=12 or len(text)>2:continue
                if len(text)==1:
                    if text=='1':continue  # Could be the intact prefix of clipped 10/11/12.
                    if not(captions and 3<line.x0<line.x1<crop.width-3
                           and max(c.y1 for c in captions)<line.y0<line.y1<crop.height-3):continue
                    single_month=True
            elif label=='DD':
                if len(text)!=2 or not 1<=int(text)<=31:continue
            elif len(text) not in {2,4}:continue
            choices.append((text,observed_confidence(line.confidence) or 0.0))
        values={value for value,_ in choices}
        parts[label]=next(iter(values)) if len(values)==1 else ''
        scores[label]=min((score for value,score in choices if value==parts[label]),default=0.0)
        attempts.append({'engine':'tesseract','reason':'DOB_LITERAL_COMPONENT_OBSERVED','dob_cell':label,
            'component_bbox':list(box),'input_size':list(crop.size),
            'observation':{'lines':[{'text':l.text,'bbox':[l.x0,l.y0,l.x1,l.y1],'confidence':l.confidence} for l in lines]},
            'preprocessing_profile':'dob_literal_caption_aware','digit_alphabet_forced':False})
        crop.close()
    if min(scores.values(),default=0.0)<=0:return None,attempts
    mm,dd,yy=(parts.get(label,'') for label in ('MM','DD','YY'))
    if not(re.fullmatch(r'[0-9]{1,2}',mm) and re.fullmatch(r'[0-9]{2}',dd) and re.fullmatch(r'[0-9]{2}|[0-9]{4}',yy)):
        return None,attempts
    value,valid=_shape_dob_text('patient_dob',f'{int(mm):02d} {dd} {yy}',allow_ordered_components=True)
    if not valid:return None,attempts
    attempts.append({'engine':'tesseract','reason':'DOB_LITERAL_COMPONENTS_COMPLETE',
        'observation':{'parts':parts,'component_confidences':scores,'qualified_single_month':single_month},
        'preprocessing_profile':'dob_literal_caption_aware','digit_alphabet_forced':False})
    return {'value':value,'raw_value':' | '.join(label+':'+parts[label] for label in ('MM','DD','YY')),
            'raw_confidence':min(scores.values()),'engine':'tesseract'},attempts
