"""SuperPoint + LightGlue correspondences for catastrophic registration.

Used only after local SIFT/orientation/document-quad exhaustion. Homography
acceptance still uses the unchanged RegistrationPolicy gates — this module
only produces denser matches when classical SIFT is sparse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class LearnedCorrespondences:
    source_xy: np.ndarray  # (N, 2) float32 in candidate pixels
    template_xy: np.ndarray  # (N, 2) float32 in reference pixels
    scores: np.ndarray  # (N,) float32
    reason: str


class CorrespondenceExtractor(Protocol):
    def extract(
        self, candidate: Image.Image, reference: Image.Image
    ) -> LearnedCorrespondences | None: ...


class SuperPointLightGlueExtractor:
    """Lazy SuperPoint detector + LightGlue matcher (cvg/LightGlue)."""

    _SHARED: "SuperPointLightGlueExtractor | None" = None

    def __init__(
        self,
        *,
        max_num_keypoints: int = 2048,
        device: str = "cpu",
        extractor: Any | None = None,
        matcher: Any | None = None,
    ) -> None:
        self._max_num_keypoints = max_num_keypoints
        self._device = device
        self._extractor = extractor
        self._matcher = matcher

    @classmethod
    def shared(cls) -> "SuperPointLightGlueExtractor":
        """Process-lifetime singleton — amortize torch/SuperPoint cold load."""
        if cls._SHARED is None:
            cls._SHARED = cls()
        return cls._SHARED

    def _load(self) -> None:
        if self._extractor is not None and self._matcher is not None:
            return
        try:
            from lightglue import LightGlue, SuperPoint
        except ImportError as exc:
            raise RuntimeError(
                "LightGlue requires optional deps: pip install '.[learned-match]'"
            ) from exc
        self._extractor = (
            SuperPoint(max_num_keypoints=self._max_num_keypoints)
            .eval()
            .to(self._device)
        )
        self._matcher = LightGlue(features="superpoint").eval().to(self._device)

    def extract(
        self, candidate: Image.Image, reference: Image.Image
    ) -> LearnedCorrespondences | None:
        self._load()
        assert self._extractor is not None and self._matcher is not None
        try:
            import torch
            from lightglue.utils import numpy_image_to_torch, rbd
        except ImportError as exc:
            raise RuntimeError(
                "LightGlue requires optional deps: pip install '.[learned-match]'"
            ) from exc

        cand = np.asarray(candidate.convert("L"), dtype=np.uint8)
        ref = np.asarray(reference.convert("L"), dtype=np.uint8)
        # Downscale very large pages for latency; scale keypoints back after.
        cand_t, cand_scale = _to_torch_gray(cand, max_side=1024)
        ref_t, ref_scale = _to_torch_gray(ref, max_side=1024)
        cand_t = cand_t.to(self._device)
        ref_t = ref_t.to(self._device)
        with torch.inference_mode():
            feats0 = self._extractor.extract(cand_t)
            feats1 = self._extractor.extract(ref_t)
            matches = rbd(self._matcher({"image0": feats0, "image1": feats1}))
            kpts0 = rbd(feats0)["keypoints"]
            kpts1 = rbd(feats1)["keypoints"]
        pairs = matches["matches"]
        if pairs is None or len(pairs) < 4:
            return None
        scores = matches.get("scores")
        idx0 = pairs[:, 0].detach().cpu().numpy()
        idx1 = pairs[:, 1].detach().cpu().numpy()
        src = kpts0.detach().cpu().numpy()[idx0] * float(cand_scale)
        dst = kpts1.detach().cpu().numpy()[idx1] * float(ref_scale)
        if scores is None:
            score_arr = np.ones(len(src), dtype=np.float32)
        else:
            score_arr = scores.detach().cpu().numpy().astype(np.float32)
        return LearnedCorrespondences(
            source_xy=src.astype(np.float32),
            template_xy=dst.astype(np.float32),
            scores=score_arr,
            reason="SUPERPOINT_LIGHTGLUE",
        )


def _to_torch_gray(gray: np.ndarray, *, max_side: int) -> tuple[Any, float]:
    from lightglue.utils import numpy_image_to_torch
    import cv2

    h, w = gray.shape[:2]
    scale = 1.0
    if max(h, w) > max_side:
        scale = max(h, w) / float(max_side)
        gray = cv2.resize(
            gray,
            (max(1, int(w / scale)), max(1, int(h / scale))),
            interpolation=cv2.INTER_AREA,
        )
    return numpy_image_to_torch(gray), scale
