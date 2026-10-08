"""Shared bounded DOB subcells; acquisition only, no acceptance authority."""
def dob_cell_bboxes(band):
    """Split a DOB digit band into MM / DD / YY cells (CMS-1500 box 3).

    Inset each cell away from the dashed vertical rules â€” those glyphs OCR as
    digit ``1`` and are the dominant source of 01â†”11 / 09â†”19 CONFLICT_MARGIN HITL.
    """
    x0, y0, x1, y1 = (int(v) for v in band)
    width = max(1, x1 - x0)
    inset = 3
    mm_x1 = x0 + int(0.34 * width)
    dd_x0 = mm_x1
    dd_x1 = x0 + int(0.62 * width)
    yy_x0 = dd_x1
    if x0 < 740 < 795 < x1:
        # CMS reference-space ruling positions do not move when the year band
        # is widened. Proportional splits otherwise include the next ruling.
        mm_x1 = dd_x0 = 740
        dd_x1 = yy_x0 = 795
        # The public blank's M sex legend begins at x=873; it is not year ink.
        x1 = min(x1, 871)
    return {
        'MM': (x0 + inset, y0, max(x0 + inset + 1, mm_x1 - inset), y1),
        'DD': (dd_x0 + inset, y0, max(dd_x0 + inset + 1, dd_x1 - inset), y1),
        'YY': (yy_x0 + inset, y0, max(yy_x0 + inset + 1, x1 - inset), y1),
    }

