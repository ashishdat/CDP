import numpy as np
from PIL import Image

from workers.field_candidates.crop_retuning import retune_cell_crop


def test_dense_cell_borders_are_inset_and_white_context_is_added() -> None:
    pixels = np.full((40, 100), 255, dtype=np.uint8)
    pixels[:, 3] = 0
    pixels[36, :] = 0
    pixels[12:28, 35:40] = 0
    result = retune_cell_crop(Image.fromarray(pixels), border_px=8)
    assert "LEFT" in result.removed_rule_edges
    assert "BOTTOM" in result.removed_rule_edges
    assert result.image.width > 16
    assert np.asarray(result.image)[0, 0] == 255


def test_crop_without_dense_edge_rule_is_not_inset() -> None:
    pixels = np.full((30, 80), 255, dtype=np.uint8)
    pixels[10:20, 30:35] = 0
    result = retune_cell_crop(Image.fromarray(pixels), border_px=4)
    assert result.inset == (0, 0, 0, 0)
    assert not result.changed
