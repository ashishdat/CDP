"""Render professional architecture diagrams for the claims IDP platform."""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "submission" / "architecture_diagrams"
WIDTH, HEIGHT = 1920, 1080
NAVY = "#061522"
PANEL = "#10283A"
PANEL_2 = "#15364A"
TEAL = "#43D7B3"
BLUE = "#67AAFF"
PURPLE = "#B28DFF"
ORANGE = "#FFB86B"
RED = "#FF8793"
WHITE = "#F2F7FC"
MUTED = "#9FB2C5"
LINE = "#29485F"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "arialbd.ttf" if bold else "arial.ttf"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size)


def text(draw: ImageDraw.ImageDraw, x: int, y: int, value: str, size: int,
         color: str = WHITE, *, bold: bool = False, width: int | None = None,
         anchor: str | None = None) -> int:
    lines = textwrap.wrap(value, width=width, break_long_words=False) if width else value.splitlines()
    for line in lines or [""]:
        draw.text((x, y), line, fill=color, font=font(size, bold), anchor=anchor)
        y += size + 8
    return y


def canvas(title: str, subtitle: str, number: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), NAVY)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 12), fill=TEAL)
    text(draw, 70, 42, "CLAIMS INTELLIGENCE · ARCHITECTURE", 18, TEAL, bold=True)
    text(draw, 70, 92, title, 40, WHITE, bold=True)
    text(draw, 70, 148, subtitle, 18, MUTED)
    text(draw, 1840, 52, number, 18, TEAL, bold=True, anchor="ra")
    draw.line((70, 205, 1850, 205), fill=LINE, width=2)
    return image, draw


def box(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], title: str,
        body: str = "", *, accent: str = TEAL, center: bool = False,
        fill: str = PANEL) -> None:
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=16, fill=fill, outline=accent, width=2)
    draw.rectangle((x1, y1, x1 + 6, y2), fill=accent)
    if center:
        text(
            draw,
            (x1 + x2) // 2,
            y1 + 25,
            title,
            19,
            WHITE,
            bold=True,
            width=max(12, (x2 - x1) // 11),
            anchor="ma",
        )
        if body:
            text(draw, (x1 + x2) // 2, y1 + 62, body, 14, MUTED, width=max(18, (x2 - x1) // 10), anchor="ma")
    else:
        text(draw, x1 + 22, y1 + 20, title, 18, WHITE, bold=True, width=max(18, (x2 - x1) // 10))
        if body:
            text(draw, x1 + 22, y1 + 55, body, 14, MUTED, width=max(18, (x2 - x1) // 10))


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int],
          color: str = TEAL, label: str | None = None) -> None:
    draw.line((*start, *end), fill=color, width=4)
    x1, y1 = start
    x2, y2 = end
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        points = [(x2, y2), (x2 - direction * 14, y2 - 9), (x2 - direction * 14, y2 + 9)]
    else:
        direction = 1 if y2 > y1 else -1
        points = [(x2, y2), (x2 - 9, y2 - direction * 14), (x2 + 9, y2 - direction * 14)]
    draw.polygon(points, fill=color)
    if label:
        text(draw, (x1 + x2) // 2, (y1 + y2) // 2 - 24, label, 12, color, bold=True, anchor="mm")


def lane(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], title: str,
         accent: str) -> None:
    draw.rounded_rectangle(xy, radius=18, fill="#0A1D2B", outline=LINE, width=2)
    x1, y1, _, _ = xy
    label_width = min(340, max(210, 115 + len(title) * 8))
    draw.rounded_rectangle((x1, y1, x1 + label_width, y1 + 42), radius=12, fill=accent)
    text(draw, x1 + label_width // 2, y1 + 11, title.upper(), 13, NAVY, bold=True, anchor="ma")


def overall_flow() -> Image.Image:
    image, draw = canvas("1 · Overall Processing Flow", "From incoming claim document to validated output and exception closure", "01 / 04")
    y = 280
    stages = [
        (70, "Input", "TIFF · PDF · PNG · JPEG", BLUE),
        (300, "Ingest", "hash · malware · idempotency", TEAL),
        (560, "Prepare pages", "decode · deskew · quality", TEAL),
        (850, "Classify & align", "family · anchors · homography", BLUE),
        (1160, "Regional evidence", "field crops · tables · blocks", PURPLE),
        (1480, "Validate & reconcile", "rules · agreement · references", TEAL),
    ]
    widths = [190, 220, 240, 260, 260, 360]
    for idx, ((x, title, body, color), width_value) in enumerate(zip(stages, widths, strict=True)):
        box(draw, (x, y, x + width_value, y + 145), title, body, accent=color, center=True)
        if idx < len(stages) - 1:
            arrow(draw, (x + width_value, y + 72), (stages[idx + 1][0] - 16, y + 72))

    box(draw, (220, 540, 530, 685), "Standard forms", "CMS-1500 · UB-04 templates", accent=TEAL, center=True)
    box(draw, (605, 540, 915, 685), "Variable documents", "invoices · statements · receipts", accent=BLUE, center=True)
    box(draw, (990, 540, 1300, 685), "OCR cascade", "Paddle · Tesseract · handwriting", accent=PURPLE, center=True)
    box(draw, (1375, 540, 1685, 685), "Crop-only LLM", "authorized unresolved evidence", accent=ORANGE, center=True)
    arrow(draw, (1290, 425), (375, 525), BLUE, "structured")
    arrow(draw, (1290, 425), (760, 525), BLUE, "unstructured")
    arrow(draw, (1290, 425), (1145, 525), PURPLE, "local cascade")
    arrow(draw, (1290, 425), (1530, 525), ORANGE, "exceptional")

    box(draw, (180, 815, 500, 960), "Automatic acceptance", "hard-valid · corroborated · policy pass", accent=TEAL, center=True)
    box(draw, (650, 815, 970, 960), "Human review", "insufficient or contradictory evidence", accent=RED, center=True)
    box(draw, (1120, 815, 1440, 960), "Canonical claim", "JSON · evidence manifest · audit", accent=BLUE, center=True)
    box(draw, (1540, 815, 1840, 960), "Outputs", "CSV · NSF/UB92 · downstream", accent=TEAL, center=True)
    arrow(draw, (1660, 425), (340, 800), TEAL, "eligible")
    arrow(draw, (1660, 425), (810, 800), RED, "fail closed")
    arrow(draw, (500, 887), (1105, 887), TEAL)
    arrow(draw, (970, 887), (1105, 887), RED)
    arrow(draw, (1440, 887), (1525, 887), TEAL)
    return image


def component_level() -> Image.Image:
    image, draw = canvas("2 · Component-Level Architecture", "Deployable services, worker pools, shared contracts and stateful platform services", "02 / 04")
    lane(draw, (60, 245, 1860, 400), "Experience & APIs", BLUE)
    for x, title, body in [(270, "Evaluation UI", "React · evidence · cost"), (690, "Ingestion API", "upload · batch · dedupe"), (1110, "Review API", "tasks · approvals · audit"), (1530, "Output API", "JSON · fixed width")]:
        box(draw, (x, 290, x + 260, 375), title, body, accent=BLUE, center=True)

    lane(draw, (60, 430, 1860, 640), "Processing workers", TEAL)
    workers = ["Document\npreparation", "Page\ndetection", "Standard form\nextraction", "Unstructured /\ntables", "Validation &\nreconciliation", "Retry / VLM\nfallback", "Output\ngeneration"]
    for idx, title in enumerate(workers):
        x = 220 + idx * 230
        box(draw, (x, 485, x + 190, 605), title, "", accent=TEAL, center=True)
        if idx < len(workers) - 1:
            arrow(draw, (x + 190, 545), (x + 220, 545), TEAL)

    lane(draw, (60, 670, 1860, 835), "Shared platform packages", PURPLE)
    packages = ["Domain & events", "Object storage", "OCR contracts", "Templates & alignment", "Validation rules", "References", "Security & observability"]
    for idx, title in enumerate(packages):
        x = 175 + idx * 240
        box(draw, (x, 725, x + 205, 805), title, "", accent=PURPLE, center=True)

    lane(draw, (60, 865, 1860, 1030), "State & external services", ORANGE)
    for x, title, body, color in [
        (220, "PostgreSQL", "metadata · outbox · audit", BLUE),
        (570, "S3 / MinIO", "documents · crops · outputs", BLUE),
        (920, "Redpanda / Kafka", "durable event backbone", TEAL),
        (1270, "Redis", "cache · coordination", PURPLE),
        (1530, "Azure OpenAI", "authorized crop fallback", ORANGE),
    ]:
        box(draw, (x, 915, x + 250, 1005), title, body, accent=color, center=True)
    return image


def tech_stack() -> Image.Image:
    image, draw = canvas("3 · Technology Stack", "Open, portable foundations with optional specialized AI services", "03 / 04")
    categories = [
        ("User experience", BLUE, ["React 18", "TypeScript", "Vite", "Nginx"]),
        ("Application services", TEAL, ["Python 3.11+", "FastAPI", "Pydantic v2", "SQLAlchemy 2"]),
        ("Document & CV", TEAL, ["OpenCV", "Pillow", "PyMuPDF", "img2table optional"]),
        ("OCR & AI", PURPLE, ["PaddleOCR", "Tesseract", "TrOCR", "Docling optional", "Azure GPT-4o"]),
        ("Data platform", BLUE, ["PostgreSQL", "Redis", "S3 / MinIO", "Redpanda / Kafka"]),
        ("Cloud native", ORANGE, ["Docker", "Kubernetes", "Helm", "KEDA", "GitHub Actions"]),
        ("Observability", TEAL, ["Prometheus", "Grafana", "OpenTelemetry", "structlog"]),
        ("Security & governance", RED, ["RBAC hook", "PHI redaction", "signed URLs", "retention", "audit trail"]),
    ]
    for idx, (title, color, items) in enumerate(categories):
        col, row = idx % 4, idx // 4
        x, y = 70 + col * 455, 255 + row * 340
        draw.rounded_rectangle((x, y, x + 410, y + 300), radius=20, fill=PANEL, outline=color, width=2)
        text(draw, x + 28, y + 25, title, 21, WHITE, bold=True, width=28)
        yy = y + 82
        for item in items:
            draw.ellipse((x + 30, yy + 5, x + 38, yy + 13), fill=color)
            text(draw, x + 52, yy, item, 17, MUTED)
            yy += 43
    box(draw, (120, 925, 1800, 1025), "Design choice", "Local open-source OCR handles the common path. Specialized GPU/cloud services are isolated adapters invoked only for unresolved regional evidence.", accent=TEAL, center=True)
    return image


def production_deployment() -> Image.Image:
    image, draw = canvas("4 · Production Deployment Architecture", "Highly available, horizontally scalable deployment for 100M+ pages/year", "04 / 04")

    box(draw, (70, 280, 260, 410), "Users / systems", "portal · API · batch", accent=BLUE, center=True)
    box(draw, (330, 280, 530, 410), "WAF + gateway", "TLS · rate limit · OIDC", accent=RED, center=True)
    box(draw, (600, 260, 875, 430), "Kubernetes ingress", "private services · network policy", accent=TEAL, center=True)
    arrow(draw, (260, 345), (315, 345), BLUE)
    arrow(draw, (530, 345), (585, 345), TEAL)

    lane(draw, (930, 240, 1850, 465), "Application namespace", BLUE)
    box(draw, (1080, 310, 1300, 420), "Ingestion API", "3+ replicas", accent=BLUE, center=True)
    box(draw, (1400, 310, 1620, 420), "Review / output", "2+ replicas", accent=BLUE, center=True)
    arrow(draw, (875, 345), (1065, 345), TEAL)

    lane(draw, (70, 500, 1240, 820), "KEDA-scaled processing namespace", TEAL)
    pools = [
        (210, 570, "CPU preparation", "decode · quality"),
        (500, 570, "CPU OCR", "Paddle · Tesseract"),
        (790, 570, "GPU / layout", "handwriting · tables"),
        (1080, 570, "Validation", "rules · reconcile"),
    ]
    for x, y, title, body in pools:
        box(draw, (x, y, x + 230, y + 130), title, body, accent=TEAL, center=True)
    box(draw, (500, 720, 790, 790), "Autoscale signals", "queue lag · latency · CPU/GPU", accent=PURPLE, center=True)

    lane(draw, (1280, 500, 1850, 820), "Approved external AI", ORANGE)
    box(draw, (1420, 570, 1720, 710), "Azure OpenAI", "private endpoint · approved region", accent=ORANGE, center=True)
    box(draw, (1420, 730, 1720, 790), "Crop-only payload", "no complete claim page", accent=RED, center=True)
    arrow(draw, (1240, 650), (1405, 650), ORANGE, "unresolved only")

    lane(draw, (70, 850, 1850, 1035), "Highly available data & operations", PURPLE)
    services = [
        (200, "Kafka / Redpanda", "multi-broker · DLQ"),
        (530, "PostgreSQL", "multi-AZ · backup · PITR"),
        (860, "Object storage", "encrypted · versioned · lifecycle"),
        (1190, "Redis", "HA cache · coordination"),
        (1520, "Observability", "Prometheus · Grafana · OTEL"),
    ]
    for x, title, body in services:
        box(draw, (x, 905, x + 270, 1000), title, body, accent=PURPLE, center=True)
    arrow(draw, (1200, 465), (1200, 835), PURPLE, "events + artifacts")
    text(draw, 90, 1045, "Cross-cutting: workload identity · secret manager · encryption · audit · retention · canary rollback · disaster recovery", 15, MUTED)
    return image


def main() -> int:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    diagrams = [
        ("01_Overall_Flow.png", overall_flow()),
        ("02_Component_Level.png", component_level()),
        ("03_Technology_Stack.png", tech_stack()),
        ("04_Production_Deployment.png", production_deployment()),
    ]
    for name, image in diagrams:
        image.save(OUTPUT / name, optimize=True)
    pdf_pages = [image.convert("RGB") for _, image in diagrams]
    pdf_pages[0].save(OUTPUT / "Architecture_Diagrams.pdf", save_all=True, append_images=pdf_pages[1:], resolution=144)
    print(f"Created {len(diagrams)} diagrams in {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
