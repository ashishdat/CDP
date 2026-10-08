"""Benchmark-only ONNX thread cap; activated explicitly by the harness."""
import os

if os.environ.get("CDP_BENCHMARK_ONNX_THREADS"):
    import cv2
    cv2.setNumThreads(1)
    from rapidocr_onnxruntime import RapidOCR

    _threads = int(os.environ["CDP_BENCHMARK_ONNX_THREADS"])
    if not 1 <= _threads <= (os.cpu_count() or 1):
        raise ValueError("Invalid benchmark ONNX thread count")
    _original_init = RapidOCR.__init__

    def _bounded_init(self, *args, **kwargs):
        kwargs.setdefault("intra_op_num_threads", _threads)
        kwargs.setdefault("inter_op_num_threads", 1)
        _original_init(self, *args, **kwargs)

    RapidOCR.__init__ = _bounded_init
