from workers.cascade.azure_read_adapter import spatial_dob_components

def word(text,x0,x1,y0,y1):return {"content":text,"polygon":[x0,y0,x1,y0,x1,y1,x0,y1]}
def inputs(merged="0130",year="1965",x0=83,x1=182):
 return tuple([word("MM",100,127,40,56),word("DD",159,183,40,56),word("YY",222,250,39,55),word(merged,x0,x1,53,81),word(year,193,261,53,81)])
def test_actual_provider_merged_word_is_spatially_bound():
 assert spatial_dob_components(inputs())=="01/30/1965"
def test_four_digits_not_spanning_both_columns_are_not_split():
 assert spatial_dob_components(inputs(x0=100,x1=130)) is None
def test_invalid_month_is_not_repaired():
 assert spatial_dob_components(inputs(merged="1330")) is None
def test_explicit_future_year_is_not_century_repaired():
 assert spatial_dob_components(inputs(year="2074")) is None

def test_actual_edge_rulings_preserve_three_observed_components():
 assert spatial_dob_components((word('02|',108,145,39,72),word('02',158,184,43,71),word('|1990',190,266,44,71)))=='02/02/1990'

def test_unknown_year_suffix_and_internal_ruling_are_not_discarded():
 for year in ('|1990MX','19|90','1990�'):
  assert spatial_dob_components((word('02',108,145,39,72),word('02',158,184,43,71),word(year,190,266,44,71))) is None

def test_nonfinite_word_geometry_fails_closed():
 assert spatial_dob_components((word('02',float('nan'),145,39,72),word('02',158,184,43,71),word('1990',190,266,44,71))) is None
