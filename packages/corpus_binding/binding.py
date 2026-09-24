"""Fail-fast binding of dataset.yaml, archive path, and selected documents.

Permanent fix for the recurring APP_FAILURE pattern: cascade defaults to the
1000-claim dataset while a sample runner points ``--zip`` / ``CDP_HACKATHON_ZIP``
at a different corpus. ``app.py`` then cannot open the document → geometry_missing
in ~1s → APP_FAILURE flood.

This module refuses to start a run unless:
1. dataset.yaml root resolves to an existing archive
2. the explicit ``--zip`` (if given) is the *same file* as dataset.root
3. every selected document path exists inside that archive

Hash verification is optional (large zips); path+membership is the hard gate.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence
from zipfile import ZipFile

import yaml

ROOT = Path(__file__).resolve().parents[2]


class CorpusBindingError(ValueError):
    """Raised when dataset / zip / documents disagree — do not start the run."""


@dataclass(frozen=True)
class CorpusBindingResult:
    dataset_id: str
    dataset_yaml: str
    archive: str
    documents_requested: int
    documents_present: int
    missing_documents: tuple[str, ...] = ()
    zip_matches_dataset_root: bool = True
    hash_checked: bool = False
    hash_ok: bool | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve(path: Path) -> Path:
    p = path if path.is_absolute() else (ROOT / path)
    return p.expanduser().resolve()


def _load_dataset_root(dataset_yaml: Path) -> tuple[str, Path]:
    cfg = yaml.safe_load(dataset_yaml.read_text(encoding="utf-8")) or {}
    if not isinstance(cfg, dict) or "dataset_id" not in cfg:
        raise CorpusBindingError(f"dataset yaml missing dataset_id: {dataset_yaml}")
    dataset_id = str(cfg["dataset_id"])
    root_raw = cfg.get("root")
    if not isinstance(root_raw, str) or not root_raw.strip():
        raise CorpusBindingError(f"dataset yaml missing root: {dataset_yaml}")
    root = Path(root_raw).expanduser()
    if not root.is_absolute():
        root = (dataset_yaml.parent / root).resolve()
    else:
        root = root.resolve()
    return dataset_id, root


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _archive_names(archive: Path) -> set[str]:
    with ZipFile(archive, "r") as zf:
        return {n.replace("\\", "/") for n in zf.namelist() if not n.endswith("/")}


def bind_corpus(
    *,
    dataset_yaml: Path | str,
    zip_path: Path | str | None = None,
    documents: Sequence[str] | None = None,
    require_documents: bool = True,
    verify_hash: bool = False,
) -> CorpusBindingResult:
    """Bind dataset ↔ zip ↔ documents. Raises CorpusBindingError on mismatch."""
    ds_path = _resolve(Path(dataset_yaml))
    if not ds_path.is_file():
        raise CorpusBindingError(f"dataset yaml not found: {ds_path}")

    dataset_id, ds_root = _load_dataset_root(ds_path)
    notes: list[str] = []

    if zip_path is None:
        archive = ds_root
        notes.append("zip_defaulted_to_dataset_root")
    else:
        archive = _resolve(Path(zip_path))

    if not archive.is_file():
        raise CorpusBindingError(
            f"archive missing for dataset_id={dataset_id}: {archive}. "
            "Download the Drive zip and point dataset.yaml root at it."
        )

    zip_matches = _same_file(archive, ds_root)
    if not zip_matches:
        raise CorpusBindingError(
            "CORPUS_ZIP_DATASET_MISMATCH: "
            f"--zip={archive} is not the same file as dataset.root={ds_root} "
            f"(dataset_id={dataset_id}). app.py loads pages from dataset.root; "
            "a different --zip only affects listing and produces APP_FAILURE."
        )

    docs = [d.replace("\\", "/").strip() for d in (documents or []) if d and d.strip()]
    missing: list[str] = []
    present = 0
    if docs:
        names = _archive_names(archive)
        for doc in docs:
            if doc in names:
                present += 1
            else:
                missing.append(doc)
        if require_documents and missing:
            sample = missing[:8]
            raise CorpusBindingError(
                "CORPUS_DOCUMENTS_MISSING: "
                f"{len(missing)}/{len(docs)} selected documents not in {archive.name} "
                f"(dataset_id={dataset_id}). examples={sample}. "
                "Wrong corpus or stale selected_documents.txt."
            )
    elif require_documents and documents is not None:
        raise CorpusBindingError("CORPUS_DOCUMENTS_EMPTY: no documents selected")

    hash_ok: bool | None = None
    hash_checked = False
    if verify_hash:
        hash_checked = True
        try:
            from datasets.registry import DatasetManager

            mgr = DatasetManager.load(ds_path)
            report = mgr.verify()
            hash_ok = bool(report.get("sha_match"))
            if not hash_ok:
                raise CorpusBindingError(
                    "CORPUS_HASH_MISMATCH: "
                    f"expected={report.get('expected_hash')} actual={report.get('actual_hash')}"
                )
            notes.append("hash_verified")
        except CorpusBindingError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CorpusBindingError(f"CORPUS_HASH_VERIFY_FAILED: {type(exc).__name__}:{exc}") from exc

    return CorpusBindingResult(
        dataset_id=dataset_id,
        dataset_yaml=str(ds_path),
        archive=str(archive),
        documents_requested=len(docs),
        documents_present=present if docs else -1,
        missing_documents=tuple(missing),
        zip_matches_dataset_root=zip_matches,
        hash_checked=hash_checked,
        hash_ok=hash_ok,
        notes=tuple(notes),
    )


def write_corpus_binding(out_dir: Path, result: CorpusBindingResult) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "corpus_binding.json"
    path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def missing_from_iterable(archive: Path, documents: Iterable[str]) -> list[str]:
    names = _archive_names(archive)
    return [d.replace("\\", "/") for d in documents if d.replace("\\", "/") not in names]
