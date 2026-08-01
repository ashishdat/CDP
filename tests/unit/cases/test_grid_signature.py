"""Grid/layout signature: fast OCR-free form-layout fingerprinting."""

from PIL import Image, ImageDraw

from tests.conftest import requires_dataset
from workers.document_preparation.codecs import decode_tiff_pages
from workers.page_detection.grid_signature import compute_grid_signature, signature_similarity


def _grid_image(cell_size=40, size=(800, 1000)) -> Image.Image:
    img = Image.new("L", size, color=255)
    draw = ImageDraw.Draw(img)
    for x in range(0, size[0], cell_size):
        draw.line([(x, 0), (x, size[1])], fill=0, width=2)
    for y in range(0, size[1], cell_size):
        draw.line([(0, y), (size[0], y)], fill=0, width=2)
    return img


def _blank_image(size=(800, 1000)) -> Image.Image:
    return Image.new("L", size, color=255)


def test_identical_images_have_similarity_one():
    img = _grid_image()
    sig_a = compute_grid_signature(img)
    sig_b = compute_grid_signature(img.copy())
    assert signature_similarity(sig_a, sig_b) > 0.999


def test_gridded_image_and_blank_image_are_dissimilar():
    sig_grid = compute_grid_signature(_grid_image())
    sig_blank = compute_grid_signature(_blank_image())
    similarity = signature_similarity(sig_grid, sig_blank)
    assert similarity < 0.5


def test_blank_signature_handles_zero_norm_gracefully():
    sig = compute_grid_signature(_blank_image())
    # should not raise or produce NaN
    assert signature_similarity(sig, sig) == signature_similarity(sig, sig)


@requires_dataset
def test_same_form_type_scans_are_more_similar_than_different_form_types(dataset_raw_dir):
    """Real-data validation: two different CMS-1500 scans (Group A) should
    have a higher grid-signature similarity than a CMS-1500 scan compared
    against a UB-04 scan (Group C) -- this is the actual discriminative
    signal page routing depends on."""

    def load(relative_path):
        data = (dataset_raw_dir / relative_path).read_bytes()
        return decode_tiff_pages(data)[0].image

    cms_a = load("Group A/M047FJFL.001")
    cms_b = load("Group A/M047FJFL.002")
    ub_a = load("Group C/M047IJBF.001")

    sig_cms_a = compute_grid_signature(cms_a)
    sig_cms_b = compute_grid_signature(cms_b)
    sig_ub_a = compute_grid_signature(ub_a)

    same_form_similarity = signature_similarity(sig_cms_a, sig_cms_b)
    cross_form_similarity = signature_similarity(sig_cms_a, sig_ub_a)

    assert same_form_similarity > cross_form_similarity
    assert same_form_similarity > 0.9
