"""Explicit dataset identities; no benchmark discovery or corpus extraction.

Usage: manager = DatasetManager.load("dataset.yaml")
       manager.describe()  # registered metadata and archive location
       manager.verify()    # read-only SHA-256 and image-frame counts
"""

from dataclasses import asdict, dataclass, replace
from enum import Enum
from hashlib import file_digest
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from zipfile import ZipFile

import yaml
from PIL import Image


class DatasetType(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    BENCHMARK = "BENCHMARK"
    VALIDATION = "VALIDATION"
    PRODUCTION = "PRODUCTION"


@dataclass(frozen=True)
class DatasetMetadata:
    dataset_id: str
    version: int
    type: DatasetType
    pages: int
    documents: int
    hash: str
    description: str
    source: str


REGISTRY = MappingProxyType({
    "DEVELOPMENT_DATASET_V1": DatasetMetadata(
        dataset_id="DEVELOPMENT_DATASET_V1",
        version=1,
        type=DatasetType.DEVELOPMENT,
        pages=2173,
        documents=1000,
        hash="8c09d4ec4de3fef8bf41771ae45bc69b69300221781a9eea9183936cfcbe85f3",
        description="Hackathon claims development corpus; not ENGINEERING_BENCHMARK_V1.",
        source="Hackathon - 1000 Claims.zip",
    ),
    # Hash is pack-time specific; YAML must supply the concrete SHA-256.
    "OPERATIONAL_E2E_100_V1": DatasetMetadata(
        dataset_id="OPERATIONAL_E2E_100_V1",
        version=1,
        type=DatasetType.VALIDATION,
        pages=284,
        documents=100,
        hash="PACK_TIME_SHA256",
        description=(
            "Frozen 100 paired Hackathon claims for operational E2E "
            "(from AnchorNormalizationDeltaReport); not the full DEVELOPMENT_DATASET_V1."
        ),
        source="Hackathon-100-ops-subset.zip",
    ),
})


@dataclass(frozen=True)
class DatasetManager:
    metadata: DatasetMetadata
    root: Path

    @classmethod
    def load(cls, path: str | Path = "dataset.yaml") -> "DatasetManager":
        """Load a registered identity; relative roots resolve beside the YAML.

        Root refers to the original ZIP, not an extracted directory. Loading
        metadata does not require the archive to be available on this machine.

        OPERATIONAL_E2E_100_V1 requires an extra YAML ``hash`` field because the
        subset archive digest is produced when the operator packs the 100 claims.
        """
        config_path = Path(path).resolve()
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or "dataset_id" not in config:
            raise ValueError("Dataset configuration must include dataset_id")
        dataset_id = config["dataset_id"]
        if not isinstance(dataset_id, str) or dataset_id not in REGISTRY:
            raise ValueError("Unknown dataset_id")
        template = REGISTRY[dataset_id]
        if dataset_id == "OPERATIONAL_E2E_100_V1":
            required = {"dataset_id", "root", "pages", "documents", "description", "hash"}
        else:
            required = {"dataset_id", "root", "pages", "documents", "description"}
        if set(config) != required:
            raise ValueError(f"Dataset configuration must contain exactly {sorted(required)}")
        for name in ("pages", "documents"):
            if type(config[name]) is not int or config[name] != getattr(template, name):
                raise ValueError(f"{name} does not match registered dataset")
        if config["description"] != template.description:
            raise ValueError("description does not match registered dataset")
        if not isinstance(config["root"], str) or not config["root"].strip():
            raise ValueError("root must be an archive path")
        if dataset_id == "OPERATIONAL_E2E_100_V1":
            digest = config["hash"]
            if not isinstance(digest, str) or len(digest) != 64:
                raise ValueError("hash must be a 64-character SHA-256 hex digest")
            metadata = replace(template, hash=digest.casefold())
        else:
            metadata = template
        root = Path(config["root"]).expanduser()
        if not root.is_absolute():
            root = config_path.parent / root
        return cls(metadata, root.resolve())

    def describe(self) -> dict:
        """Return JSON-serializable metadata; hash means SHA-256 of ZIP bytes."""
        return {**asdict(self.metadata), "type": self.metadata.type.value,
                "root": str(self.root), "hash_algorithm": "SHA256"}

    def verify(self) -> dict:
        """Verify ZIP bytes, file count and image frames without disk extraction.

        One non-directory ZIP entry is one document; each image frame is a
        page. Unsupported/corrupt images fail verification. No OCR is invoked.
        Missing or invalid archives raise their original I/O/ZIP exception.
        """
        pages = 0
        errors = []
        with self.root.open("rb") as stream:
            archive_hash = file_digest(stream, "sha256").hexdigest()
            stream.seek(0)
            with ZipFile(stream, "r") as archive:
                entries = [entry for entry in archive.infolist() if not entry.is_dir()]
                for entry in entries:
                    try:
                        with archive.open(entry, "r") as document:
                            payload = document.read()
                        with Image.open(BytesIO(payload)) as image:
                            pages += image.n_frames
                    except (OSError, ValueError, EOFError) as exc:
                        errors.append({"file": entry.filename, "error": str(exc)})
            stream.seek(0)
            unchanged = file_digest(stream, "sha256").hexdigest() == archive_hash
        sha_match = archive_hash == self.metadata.hash
        counts_match = len(entries) == self.metadata.documents and pages == self.metadata.pages
        return {
            "dataset_id": self.metadata.dataset_id,
            "verified": sha_match and counts_match and unchanged and not errors,
            "expected_documents": self.metadata.documents,
            "actual_documents": len(entries),
            "expected_pages": self.metadata.pages,
            "actual_pages": pages,
            "expected_hash": self.metadata.hash,
            "actual_hash": archive_hash,
            "sha_match": sha_match,
            "counts_match": counts_match,
            "archive_unchanged": unchanged,
            "errors": errors,
        }
