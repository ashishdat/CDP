# Test failure classification

The two template-reference failures were product configuration failures:
committed templates referenced operator-supplied images that were not present.
The references are now explicitly `null`; deployments may inject approved
blank reference images without committing claim scans.

Three failures observed on the Windows workstation occurred before test code
ran because pytest could not create directories below the user TEMP root.
They are platform/environment failures, not product regressions. CI runs pytest
with a workspace-owned base temporary directory:

```powershell
python -m pytest --basetemp evaluation_results/pytest-tmp
```

No product test is skipped. If the workspace-owned directory is unavailable,
CI must report an infrastructure failure separately rather than converting it
to a passing or quarantined product test.
