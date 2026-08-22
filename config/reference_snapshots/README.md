# Reference snapshots

Each approved local snapshot has its own directory containing `manifest.json` and a checksummed `records.json`. Runtime configuration should mount sensitive enterprise snapshots; do not commit member or provider records here.

Supported domains are `MEMBER`, `PROVIDER`, `ICD`, `CPT`, `HCPCS`, and `PAYER`. Test snapshots must set the provider's `test_only` flag and can never become evaluation-eligible reference truth.
