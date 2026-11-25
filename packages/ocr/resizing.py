"""Shared crop resizing used by recognition and retry adapters."""

from PIL import Image

UPSCALE_FACTOR = 2.0


def upscale(image: Image.Image, factor: float = UPSCALE_FACTOR) -> Image.Image:
    new_size = (int(image.width * factor), int(image.height * factor))
    return image.resize(new_size, Image.Resampling.LANCZOS)
