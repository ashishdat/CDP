from evaluation.build_dataset_labels import _slice


def test_fixed_width_slice_is_one_based_and_inclusive():
    assert _slice("ABCDEFGHIJ", 3, 6) == "CDEF"
