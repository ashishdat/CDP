FROM python:3.11-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "paddlepaddle>=3,<4" "paddleocr>=3.7,<4" pillow numpy pyyaml psutil
COPY packages ./packages
COPY workers ./workers
COPY evaluation ./evaluation
COPY config ./config
ENTRYPOINT ["python", "-m", "evaluation.run_ppocr_next_shadow"]
