from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


def _cell(reference: str, value: object, style: int = 0) -> str:
    rendered = "" if value is None else json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
    return f'<c r="{reference}" t="inlineStr" s="{style}"><is><t>{escape(rendered)}</t></is></c>'


def _column(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _sheet(headers: list[str], rows: list[dict], style_key: str | None = None) -> str:
    xml_rows = [f'<row r="1">{"".join(_cell(f"{_column(i)}1", h) for i, h in enumerate(headers, 1))}</row>']
    styles = {"PENDING": 1, "REFERENCE_NOT_FOUND": 1, "REFERENCE_VERIFIED": 2,
              "DOWNSTREAM_VERIFIED": 2, "CORRECTION_VERIFIED": 2,
              "REFERENCE_CONTRADICTION": 3, "CIRCULAR_LINEAGE_REJECTED": 3,
              "PROVIDER_UNAUTHORIZED": 3, "REVIEW_REQUIRED": 4}
    for row_number, row in enumerate(rows, 2):
        style = styles.get(str(row.get(style_key, "")), 0) if style_key else 0
        cells = "".join(_cell(f"{_column(index)}{row_number}", row.get(header), style)
                        for index, header in enumerate(headers, 1))
        xml_rows.append(f'<row r="{row_number}">{cells}</row>')
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>'


def write_enriched_workbook(path: Path, original: list[dict], decisions: list[dict], metrics: dict,
                            audit: list[dict]) -> None:
    by_key = {row["identity_key"]: row for row in decisions}
    enriched = []
    for row in original:
        canonical = "|".join((row["document_id"], row["page_number"], row["document_family"], "", row["field_name"]))
        decision = by_key[canonical]
        enriched.append({**row, "reference_value": decision["reference_value"],
            "decision": decision["decision"],
            "approved_by": decision.get("approved_by", ""),
            "approved_at": decision.get("approved_at", ""),
            "second_approved_by": decision.get("second_approved_by", ""),
            "second_approved_at": decision.get("second_approved_at", ""),
            "label_strength": decision.get("label_strength", ""),
            "source_tier": decision["source_tier"],
            "reference_provider": decision["reference_provider"],
            "reference_dataset_version": decision["reference_dataset_version"],
            "source_record_id": decision["source_record_id"], "source_lineage": decision["source_lineage"],
            "matching_attributes": decision["matching_attributes"], "contradictions": decision["contradictions"],
            "independent_truth": decision["independent_truth"], "approval_method": decision["approval_method"],
            "evaluation_eligible": decision["evaluation_eligible"],
            "decision_reason": decision["decision_reason"]})
    summary = [{"Metric": key, "Value": value} for key, value in metrics.items()]
    policy = [
        {"Tier": "TIER_A_REFERENCE", "Rule": "Authorized + independent + versioned + multi-attribute + no contradiction"},
        {"Tier": "TIER_A_APPROVED_CORRECTION", "Rule": "Primary approval; independent second approval for critical; revalidated"},
        {"Tier": "TIER_B_DOWNSTREAM", "Rule": "Finalized + independent non-circular lineage + verified field mapping"},
    ]
    codebook = [{"Value": name, "Meaning": meaning} for name, meaning in (
        ("REFERENCE_VERIFIED", "Accepted authoritative reference"),
        ("DOWNSTREAM_VERIFIED", "Accepted independently finalized downstream value"),
        ("CORRECTION_VERIFIED", "Accepted governed human correction"),
        ("PENDING", "No eligible source decision"),
        ("TEST_ONLY", "Never production or evaluation eligible"),
    )]
    sheets = [
        ("Reference Decisions", list(enriched[0]) if enriched else [], enriched, "decision"),
        ("Summary", ["Metric", "Value"], summary, None),
        ("Source Audit", list(audit[0]) if audit else ["request_id", "provider", "match_count", "latency_ms", "error"], audit, None),
        ("Approval Policy", ["Tier", "Rule"], policy, None),
        ("Codebook", ["Value", "Meaning"], codebook, None),
    ]
    content_types = ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, 6))
    workbook_sheets = ''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, *_rest) in enumerate(sheets, 1))
    relationships = ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, 6))
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", f'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{content_types}</Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{workbook_sheets}</sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relationships}<Relationship Id="rId6" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        archive.writestr("xl/styles.xml", '<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="6"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFF4CC"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="D9EAD3"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="F4CCCC"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FCE5CD"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="5"><xf/><xf fillId="2" applyFill="1"/><xf fillId="3" applyFill="1"/><xf fillId="4" applyFill="1"/><xf fillId="5" applyFill="1"/></cellXfs></styleSheet>')
        for index, (_name, headers, rows, style_key) in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet(headers, rows, style_key))
