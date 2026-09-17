"""Live OCR smoke check using synthetic text and the application's adapters."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from workers.cascade.tesseract_adapter import TesseractTextExtractor
from workers.page_detection.text_extraction import PaddleOCRTextExtractor, RapidOCRTextExtractor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=['rapidocr', 'tesseract', 'paddleocr'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = {'engine': args.engine, 'python': sys.executable,
              'checked_at': datetime.now(timezone.utc).isoformat(), 'versions': {}, 'checks': []}
    for package in ['rapidocr-onnxruntime', 'onnxruntime', 'paddleocr', 'paddlepaddle', 'Pillow']:
        try:
            report['versions'][package] = version(package)
        except PackageNotFoundError:
            report['versions'][package] = None
    try:
        engine = {'rapidocr': RapidOCRTextExtractor, 'tesseract': TesseractTextExtractor,
                  'paddleocr': PaddleOCRTextExtractor}[args.engine]()
        font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 36)
        for expected in ['HELLO WORLD', '1234567890', 'TOTAL 123.45']:
            image = Image.new('RGB', (1000, 220), 'white')
            ImageDraw.Draw(image).text((100, 80), expected, font=font, fill='black')
            for attempt in range(2):
                start = time.perf_counter()
                lines = engine.extract_region(image, 70, 50, 930, 180)
                elapsed = time.perf_counter() - start
                actual = ' '.join(line.text for line in lines).strip()
                geometry_ok = bool(lines) and all(
                    70 <= line.x0 < line.x1 <= 930 and 50 <= line.y0 < line.y1 <= 180
                    and 0 <= line.confidence <= 1 for line in lines)
                report['checks'].append({'expected': expected, 'actual': actual,
                    'attempt': attempt + 1, 'seconds': round(elapsed, 3),
                    'geometry_ok': geometry_ok, 'pass': actual == expected and geometry_ok})
        report['pass'] = all(check['pass'] for check in report['checks'])
    except Exception as exc:
        report.update({'pass': False, 'error': f'{type(exc).__name__}: {exc}'})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
