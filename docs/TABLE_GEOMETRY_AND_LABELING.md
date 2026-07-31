# Table geometry and labeling

The original `table-shadow-v2` 150-cell queue is quarantined because its
source crop geometry was not validated. Its labels are neither evaluation nor
training eligible.

Fixed CMS-1500 02/12 and UB-04 2014 pages use versioned semantic templates in
`config/table_templates`. Pages are registered to the canonical frame and
rejected when anchor residual error exceeds the configured threshold.
Template cells are cropped with inward padding that cannot cross neighbouring
cell boundaries.

Rows are classified before cells are emitted:

- `ACTIVE`: at least two independent service-line evidence fields contain ink.
- `UNUSED`: no service evidence; no labeling tasks are created.
- `AMBIGUOUS`: one evidence field; the complete row must be reviewed first.

Every crop passes image/hash, bbox, registration, header, row-state, edge-ink
and grid-line checks. Only `VALID_SINGLE_CELL` reaches the pilot manifest.
Variable laboratory invoices and statements retain anchor-gated table
geometry, with conservative internal trimming.

The reviewer sees complete-row context and the isolated cell. OCR is explicitly
an unverified suggestion. Values start blank and the disposition starts at
`PENDING_REVIEW`. Reviewer identity is supplied by authenticated request
context (`X-Reviewer-ID`) or the local operator session environment. Critical
or corrected values require a later approval by a different reviewer.

The 30-cell pilot must pass crop QA before any OCR accuracy measurement. It
contains 10 UB-04, 10 CMS-1500, five laboratory-invoice and five statement
cells. The 150-cell exercise remains stopped until this pilot is visually
confirmed as well as mechanically valid.
