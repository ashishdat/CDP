import numpy as np
from workers.page_detection.template_alignment import _template_sift_cache_key


def test_unsampled_caption_change_cannot_reuse_old_template_descriptors():
    original=np.full((128,128),255,dtype=np.uint8)
    changed=original.copy();changed[1,1]=0
    assert np.array_equal(original[::2,::2],changed[::2,::2])
    assert _template_sift_cache_key(original,3000) != _template_sift_cache_key(changed,3000)


def test_descriptor_cache_separates_dimensions_and_feature_budget():
    image=np.full((16,32),255,dtype=np.uint8)
    assert _template_sift_cache_key(image,3000) != _template_sift_cache_key(image.reshape(32,16),3000)
    assert _template_sift_cache_key(image,3000) != _template_sift_cache_key(image,6000)
