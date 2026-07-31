"""Minimal server-rendered review UI -- plain HTML, no templating engine
or frontend build step, per the platform spec's "basic React OR
server-rendered review interface" option. Every dynamic value is escaped
with `html.escape` (reviewer-submitted `reason`/`new_value` text
included) to avoid reflecting untrusted input back as markup.
"""

from __future__ import annotations

from html import escape

from apps.human_review_api.schemas import ReviewTaskDetail, ReviewTaskSummary

_PAGE_STYLE = """
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ddd; padding: 0.5rem; text-align: left; }
  th { background: #f4f4f4; }
  .crop { max-width: 400px; border: 1px solid #ccc; }
  .errors { color: #b00020; }
  form { margin-top: 1rem; }
  label { display: block; margin-top: 0.5rem; }
  input[type=text], textarea { width: 100%; max-width: 500px; padding: 0.4rem; }
  button { margin-top: 0.75rem; padding: 0.5rem 1rem; }
</style>
"""


def render_task_list(tasks: list[ReviewTaskSummary]) -> str:
    rows = "".join(
        f"<tr><td><a href='/ui/review-tasks/{t.task_id}'>{escape(str(t.task_id))}</a></td>"
        f"<td>{escape(t.field_name)}</td><td>{escape(t.status)}</td>"
        f"<td>{escape(t.created_at.isoformat())}</td></tr>"
        for t in tasks
    )
    return f"""<!doctype html><html><head><title>Review Queue</title>{_PAGE_STYLE}</head>
<body>
<h1>Open Review Tasks ({len(tasks)})</h1>
<table>
<tr><th>Task</th><th>Field</th><th>Status</th><th>Created</th></tr>
{rows}
</table>
</body></html>"""


def render_task_detail(task: ReviewTaskDetail) -> str:
    crop_html = (
        f"<img class='crop' src='{escape(task.crop_signed_url)}' alt='field crop'>"
        if task.crop_signed_url
        else "<p><em>No crop evidence available.</em></p>"
    )
    ocr_html = "".join(f"<li>{escape(c)}</li>" for c in task.ocr_candidates) or "<li>(none)</li>"
    vlm_html = escape(task.vlm_candidate) if task.vlm_candidate else "(not requested)"
    errors_html = (
        "".join(f"<li>{escape(e)}</li>" for e in task.validation_errors)
        if task.validation_errors
        else "<li>(none)</li>"
    )
    return f"""<!doctype html><html><head><title>Review: {escape(task.field_name)}</title>{_PAGE_STYLE}</head>
<body>
<p><a href="/ui/review-tasks">&larr; back to queue</a></p>
<h1>{escape(task.field_name)}</h1>
<p>Status: <strong>{escape(task.status)}</strong> &middot; Page {task.page_number}</p>

<h2>Source crop</h2>
{crop_html}

<h2>OCR candidates</h2>
<ul>{ocr_html}</ul>

<h2>VLM candidate</h2>
<p>{vlm_html}</p>

<h2 class="errors">Validation errors</h2>
<ul class="errors">{errors_html}</ul>

<h2>Correct this field</h2>
<form method="post" action="/ui/review-tasks/{task.task_id}/correct">
  <label>Reviewer <input type="text" name="reviewer" required></label>
  <label>Corrected value <input type="text" name="new_value" required></label>
  <label>Reason <textarea name="reason" required></textarea></label>
  <button type="submit">Approve with correction</button>
</form>

<h2>Reject</h2>
<form method="post" action="/ui/review-tasks/{task.task_id}/reject">
  <label>Reviewer <input type="text" name="reviewer" required></label>
  <label>Reason <textarea name="reason" required></textarea></label>
  <button type="submit">Reject</button>
</form>
</body></html>"""
