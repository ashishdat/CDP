from packages.extraction_recovery import measured_dob_geometry as m

def components():
    boxes=[(702,421,718,440),(719,421,736,440),(758,421,771,440),(771,420,789,440),
           (827,421,847,440),(849,421,861,440),(867,421,879,440),(874,441,883,452)]
    return [{'box':dict(zip(('x0','y0','x1','y1'),b)),'area':100} for b in boxes]

def test_year_crop_includes_crossing_glyph_and_excludes_lower_sex_legend():
    result=m.measured_year_recovery((672,420,883,465),components())
    assert result['year_bbox']==[798,420,882,442]
    assert all(b[3]==440 for b in result['year_ink_boxes'])
    assert result['acceptance_authority']=='NONE'

def test_incoherent_or_missing_row_does_not_change_crops():
    boxes=components();boxes[0]['box']['y1']=455
    assert m.measured_year_recovery((672,420,883,465),boxes) is None
    assert m.measured_year_recovery((672,420,883,465),[]) is None

def test_sex_ink_entirely_beyond_legacy_boundary_is_not_year_clipping():
    boxes=components();boxes[6]['box']['x0']=874
    assert m.measured_year_recovery((672,420,883,465),boxes) is None
