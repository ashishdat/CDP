FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir "paddlepaddle>=3,<4" "paddleocr>=3,<4" pillow numpy
COPY workers ./workers

CMD ["python", "-c", "from workers.ppocr_v5 import PPOCRv5Adapter; PPOCRv5Adapter()._load(); print('PP-OCRv5 ready')"]
