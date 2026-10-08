"""Bind accepted geometry to the exact template definition used to create it."""
import hashlib
import json


def template_fingerprint(template) -> str:
    payload = json.dumps(template.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
