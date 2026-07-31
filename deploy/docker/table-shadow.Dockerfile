FROM python:3.11-slim

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    "img2table>=1.4,<2" \
    "pytesseract>=0.3.13,<1" \
    "Pillow==11.2.1" \
    "opencv-python-headless>=4.10,<5" \
    "PyYAML>=6,<7" \
    "pydantic>=2.6,<3"
COPY evaluation ./evaluation
COPY config ./config
ENTRYPOINT ["python", "-m", "evaluation.run_img2table_shadow"]
