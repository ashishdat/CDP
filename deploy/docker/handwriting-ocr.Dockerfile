FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY packages ./packages
COPY workers ./workers
COPY evaluation ./evaluation
COPY config ./config
# Install CPU-only PyTorch first. The default Linux PyPI wheel currently
# brings several gigabytes of CUDA libraries that this low-cost worker does
# not use.
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    "torch==2.4.1"
RUN pip install --no-cache-dir ".[handwriting]"

ENV HF_HOME=/models/huggingface
CMD ["python", "-c", "from packages.settings import get_settings; from workers.unstructured_extraction.trocr_adapter import TrOCRAdapter; s=get_settings(); TrOCRAdapter(s.trocr_model_name, s.trocr_device, s.trocr_min_confidence)._load(); print('TrOCR ready')"]
