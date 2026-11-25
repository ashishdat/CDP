"""Create a dependency-free Excel template for participant benchmark submissions."""
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED
import xml.etree.ElementTree as ET

OUTPUT = Path(__file__).resolve().parents[1] / 'templates' / 'Participant_Sample_Evaluation.xlsx'
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'

def col(n):
    out = ''
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out

def cell(ref, value='', style=0):
    if value == '':
        return f'<c r="{ref}" s="{style}"/>'
    if isinstance(value, str) and value.startswith('='):
        return f'<c r="{ref}" s="{style}"><f>{escape(value[1:])}</f></c>'
    if isinstance(value, (float, int)):
        return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'

def validation(rng, kind, f1, f2=None):
    operator = ' operator="between"' if f2 is not None else ''
    body = f'<formula1>{escape(f1)}</formula1>'
    if f2 is not None:
        body += f'<formula2>{escape(f2)}</formula2>'
    return f'<dataValidation type="{kind}"{operator} allowBlank="1" showErrorMessage="1" errorStyle="stop" errorTitle="Check entry" error="Choose a listed value or enter a non-negative number within range." sqref="{rng}">{body}</dataValidation>'

def sheet(headers, rows, widths=None, formulas=None, validations=None, filter_rows=True):
    widths = widths or [24] * len(headers)
    columns = ''.join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i,w in enumerate(widths,1))
    content = '<row r="1" ht="42" customHeight="1">' + ''.join(cell(f'{col(i)}1',v,1) for i,v in enumerate(headers,1)) + '</row>'
    for rn, row in enumerate(rows,2):
        content += f'<row r="{rn}" ht="32" customHeight="1">'
        for i in range(1,len(headers)+1):
            value = row[i-1] if i <= len(row) else ''
            style = 2
            if formulas and i in formulas:
                value, style = formulas[i](rn)
            content += cell(f'{col(i)}{rn}',value,style)
        content += '</row>'
    end = len(rows)+1
    extras = f'<autoFilter ref="A1:{col(len(headers))}{end}"/>' if filter_rows else ''
    if validations:
        extras += f'<dataValidations count="{len(validations)}">' + ''.join(validations) + '</dataValidations>'
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{NS}"><dimension ref="A1:{col(len(headers))}{end}"/><sheetViews><sheetView workbookViewId="0"><pane xSplit="2" ySplit="1" topLeftCell="C2" activePane="bottomRight" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="32"/><cols>{columns}</cols><sheetData>{content}</sheetData>{extras}</worksheet>'

instructions = [
    ['Purpose','Shared participant evaluation workbook for document-processing samples. No benchmark results are pre-filled.'],
    ['1. Register samples','Enter canonical sample IDs, group, document type and case counts in Samples. Groups A-D are suggested from this repository; confirm counts before use.'],
    ['2. Enter results','Use one Results row per participant + sample + run. Repeated trials use distinct Run IDs. Keep IDs consistent across sheets.'],
    ['3. Record tools','Use one Pipeline Tools row per phase for the same participant + sample + run. Record tool/model version, settings and phase latency.'],
    ['4. Compare participants','Enter participant/team names in Summary column A. Summary aggregates every run for that participant; repeated samples are counted again.'],
    ['Input vs calculated','Blue text cells are inputs; shaded dark-text cells are formulas. Blank means not measured; enter 0 only when measured as zero.'],
    ['Case definition','One claim/document bundle is one case, including its attachments. Pages are tracked separately.'],
    ['Cases attempted','Cases actually submitted in this run. Cases processed = successfully completed output; failed = attempted minus processed.'],
    ['STP definition','Straight-through processing: successful cases completed with no human intervention / cases attempted. Enter only successful no-touch cases in STP count.'],
    ['Human review','Enter successfully processed cases that required human intervention. STP count + human-reviewed completed count must equal processed count.'],
    ['Case accuracy','Correct cases / cases evaluated against agreed ground truth. A correct case meets all required output criteria. Evaluated cases must be a subset of processed cases.'],
    ['Field accuracy','Correct fields / evaluated fields. Agree on field set, normalization and matching rules; describe them in notes. Keep case and field accuracy distinct.'],
    ['Latency','Seconds per attempted case, from submission to final outcome. Enter mean, P50 and P95 from measured timings. State whether human wait, retries and queue time are included.'],
    ['Summary latency','Mean latency is weighted by attempted-case count only for rows with measured mean latency. Per-run percentiles cannot be combined into a valid overall percentile.'],
    ['Wall time & throughput','Wall time = elapsed seconds for the whole run. Throughput = processed cases / wall time x 60. Summed-run throughput does not represent simultaneous aggregate capacity.'],
    ['Comparability','Use the same sample IDs, ground truth, scope, environment and concurrency when comparing participants. Record differences in notes.'],
    ['Evidence','Link to benchmark reports/logs or ground-truth versions. Use sample IDs instead of patient details.'],
    ['Capacity','Results supports 200 submissions; Pipeline Tools supports 500 phase rows; Summary supports 50 participants. Extend formulas and validation when adding rows.'],
    ['Checks','Results checks flag missing identifiers, duplicate participant/sample/run keys and inconsistent counts. Summary includes flagged rows; resolve checks before comparisons.'],
]
result_headers = ['Participant / team','Sample ID','Run ID','Run date (YYYY-MM-DD)','Sample group','Document type','Cases in sample','Cases attempted','Cases processed','Cases failed (auto)','STP cases (no human touch)','Human-reviewed completed cases','STP % (auto)','Cases evaluated','Correct cases','Case accuracy % (auto)','Fields evaluated','Correct fields','Field accuracy % (auto)','Pages processed','Mean latency (sec/case)','P50 latency (sec/case)','P95 latency (sec/case)','Run wall time (sec)','Throughput (cases/min, auto)','Environment / hardware','Concurrency','Evidence / report link','Notes / matching & timing scope','Entry check (auto)']
formulas = {
    10: lambda r:(f'=IF(OR(H{r}="",I{r}=""),"",H{r}-I{r})',3),
    13: lambda r:(f'=IF(OR(H{r}="",H{r}=0,K{r}=""),"",K{r}/H{r})',4),
    16: lambda r:(f'=IF(OR(N{r}="",N{r}=0,O{r}=""),"",O{r}/N{r})',4),
    19: lambda r:(f'=IF(OR(Q{r}="",Q{r}=0,R{r}=""),"",R{r}/Q{r})',4),
    25: lambda r:(f'=IF(OR(I{r}="",X{r}="",X{r}=0),"",I{r}/X{r}*60)',5),
    30: lambda r:(f'=IF(COUNTA(A{r}:I{r},K{r}:L{r},N{r}:O{r},Q{r}:R{r},T{r}:X{r},Z{r}:AC{r})=0,"",IF(OR(A{r}="",B{r}="",C{r}=""),"Missing IDs",IF(COUNTIFS(A$2:A$201,A{r},B$2:B$201,B{r},C$2:C$201,C{r})>1,"Duplicate run",IF(OR(H{r}="",I{r}="",K{r}="",L{r}=""),"Missing case counts",IF(OR(AND(G{r}<>"",H{r}>G{r}),I{r}>H{r},K{r}+L{r}<>I{r},N{r}>I{r},O{r}>N{r},R{r}>Q{r},AND(O{r}<>"",N{r}=""),AND(R{r}<>"",Q{r}=""),AND(U{r}<>"",W{r}<>"",V{r}>W{r})),"Check counts / latency","OK")))))',3),
}
valids = [validation('E2:E201','list','"A,B,C,D,Other"'),validation('F2:F201','list','"CMS-1500,UB-04,Unstructured,Mixed,Other"')]
for c in ['G','H','I','K','L','N','O','Q','R','T','AA']:
    valids.append(validation(f'{c}2:{c}201','whole','0','1000000000'))
for c in ['U','V','W','X']:
    valids.append(validation(f'{c}2:{c}201','decimal','0','1000000000'))
phase_headers = ['Participant / team','Sample ID','Run ID','Phase','Tool / framework','Model / engine','Version','Configuration / prompt / rules','Execution mode','Input cases','Output cases','Mean phase latency (sec/case)','Failures / retries','Notes / evidence link']
phases = 'Ingestion,Preparation,Classification,OCR,Extraction,Validation,Human review,Output,Orchestration,Other'
phase_valids = [validation('D2:D501','list',f'"{phases}"'),validation('I2:I501','list','"Automated,Manual,Hybrid"'),validation('J2:K501','whole','0','1000000000'),validation('L2:L501','decimal','0','1000000000')]
summary_headers = ['Participant / team','Runs submitted','Cases attempted','Cases processed','Failed cases','STP cases','STP %','Cases evaluated','Correct cases','Case accuracy %','Fields evaluated','Correct fields','Field accuracy %','Weighted mean latency (sec/case)','Cases/min over summed run times','Rows needing attention']
summary_formulas = {}
for i, source in {3:'H',4:'I',5:'J',6:'K',8:'N',9:'O',11:'Q',12:'R'}.items():
    summary_formulas[i] = lambda r,s=source:(f'=IF(A{r}="","",SUMIF(Results!A$2:A$201,A{r},Results!{s}$2:{s}$201))',3)
summary_formulas[2] = lambda r:(f'=IF(A{r}="","",COUNTIF(Results!A$2:A$201,A{r}))',3)
for i,n,d in [(7,'F','C'),(10,'I','H'),(13,'L','K')]:
    summary_formulas[i] = lambda r,n=n,d=d:(f'=IF(OR(A{r}="",{d}{r}=0),"",{n}{r}/{d}{r})',4)
summary_formulas[14] = lambda r:(f'=IF(A{r}="","",IFERROR(SUMPRODUCT((Results!A$2:A$201=A{r})*Results!H$2:H$201*Results!U$2:U$201)/SUMIFS(Results!H$2:H$201,Results!A$2:A$201,A{r},Results!U$2:U$201,"<>"),""))',5)
summary_formulas[15] = lambda r:(f'=IF(A{r}="","",IFERROR(SUMIFS(Results!I$2:I$201,Results!A$2:A$201,A{r},Results!X$2:X$201,">0")/SUMIF(Results!A$2:A$201,A{r},Results!X$2:X$201)*60,""))',5)
summary_formulas[16] = lambda r:(f'=IF(A{r}="","",COUNTIFS(Results!A$2:A$201,A{r},Results!AD$2:AD$201,"<>OK"))',3)

sheets = [
    ('Instructions',sheet(['Item','Guidance'],instructions,[30,125],filter_rows=False)),
    ('Samples',sheet(['Sample ID','Sample group','Document type','Cases in sample','Pages in sample','Ground truth version / link','Description / scope'],[['']*7 for _ in range(50)],[24,20,24,20,20,45,65],validations=[validation('B2:B51','list','"A,B,C,D,Other"'),validation('D2:E51','whole','0','1000000000')])),
    ('Results',sheet(result_headers,[[] for _ in range(200)],[25,24,20,24,18,22]+[20]*19+[30,18,45,65,27],formulas,valids)),
    ('Pipeline Tools',sheet(phase_headers,[[] for _ in range(500)],[25,24,20,24,30,28,20,60,20,18,18,26,35,55],validations=phase_valids)),
    ('Summary',sheet(summary_headers,[[] for _ in range(50)],[25]+[22]*12+[32,32,25],summary_formulas)),
]
styles = f'''<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="{NS}"><fonts count="3"><font><sz val="11"/><name val="Calibri"/><color rgb="FF243746"/></font><font><b/><sz val="11"/><name val="Calibri"/><color rgb="FFFFFFFF"/></font><font><sz val="11"/><name val="Calibri"/><color rgb="FF1765AC"/></font></fonts><fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF173D52"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE8F1F5"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="6"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="10" fontId="0" fillId="3" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="2" fontId="0" fillId="3" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''

def main():
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(OUTPUT,'w',ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'+''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(sheets)+1))+'</Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_) in enumerate(sheets,1))+'</sheets><calcPr calcId="191029" fullCalcOnLoad="1" forceFullCalc="1"/></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))+f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml',styles)
        for i,(_,xml) in enumerate(sheets,1):
            z.writestr(f'xl/worksheets/sheet{i}.xml',xml)
    with ZipFile(OUTPUT) as z:
        assert z.testzip() is None
        for name in z.namelist():
            ET.fromstring(z.read(name))
    print(f'Created and checked {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)')

if __name__ == '__main__':
    main()
