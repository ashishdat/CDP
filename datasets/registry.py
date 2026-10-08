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
    "DEVELOPMENT_DATASET_HACKATHON_5000_V1": DatasetMetadata(
        dataset_id="DEVELOPMENT_DATASET_HACKATHON_5000_V1",
        version=1,
        type=DatasetType.DEVELOPMENT,
        pages=10341,
        documents=5000,
        hash="af745a75d730fc0da38c036401c804c3812b0d2db9217f39068e6685c0b1eaa1",
        description=(
            "Hackathon 5000 Claims Drive corpus "
            "(id=1ohv3muiEChPU6pqR0sj7ansqUYq7odIY); not ENGINEERING_BENCHMARK_V1."
        ),
        source="Hackathon - 5000 Claims.zip",
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
    # BEGIN benchmark_4x50_20261004 sample registrations
    "HACKATHON_SAMPLE_300_50_V1": DatasetMetadata(
        dataset_id="HACKATHON_SAMPLE_300_50_V1", version=1, type=DatasetType.VALIDATION,
        pages=92, documents=50, hash="8f104b6cba7beefde6ca32316a47c4448d89f3c2b8509d706a5cedb0a32881fc",
        description='50-document stratified development sample from Hackathon 300-document pool; seed 20261004; not an independent holdout.', source="benchmark_4x50_20261004/corpus_300/sample_50.zip",
    ),
    "HACKATHON_SAMPLE_1000_50_V1": DatasetMetadata(
        dataset_id="HACKATHON_SAMPLE_1000_50_V1", version=1, type=DatasetType.VALIDATION,
        pages=86, documents=50, hash="75cada520bb5ea099dafee82f809cbeeb09b7849cacdb3122e670faf7da48c5e",
        description='50-document stratified development sample from Hackathon 1000-document pool; seed 20261004; not an independent holdout.', source="benchmark_4x50_20261004/corpus_1000/sample_50.zip",
    ),
    "HACKATHON_SAMPLE_5000_50_V1": DatasetMetadata(
        dataset_id="HACKATHON_SAMPLE_5000_50_V1", version=1, type=DatasetType.VALIDATION,
        pages=81, documents=50, hash="de5e46d672b7ef373c52d3a809822516bacc6f471c8641d763a437079645e94a",
        description='50-document stratified development sample from Hackathon 5000-document pool; seed 20261004; not an independent holdout.', source="benchmark_4x50_20261004/corpus_5000/sample_50.zip",
    ),
    "HACKATHON_SAMPLE_10000_50_V1": DatasetMetadata(
        dataset_id="HACKATHON_SAMPLE_10000_50_V1", version=1, type=DatasetType.VALIDATION,
        pages=96, documents=50, hash="bc2c7c89cd7cd2e8f23a175d04697ca71d89cd7db4fc3874f831e60c85ca5eda",
        description='50-document stratified development sample from Hackathon 10000-document pool; seed 20261004; not an independent holdout.', source="benchmark_4x50_20261004/corpus_10000/sample_50.zip",
    ),
    # END benchmark_4x50_20261004 sample registrations

    # Fixed review draws, 2026-10-05
    'HACKATHON_REVIEW_100_10_20261005': DatasetMetadata(dataset_id='HACKATHON_REVIEW_100_10_20261005', version=1, type=DatasetType.VALIDATION, pages=10, documents=10, hash='f03db26c2ac307d6bf693b14e8e4a2834a65fb4e518ffb4e8d9bb4f9205ffeb9', description='Ten-document development draw from hackathon 100 pool; seed 20261105; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_20261005\\corpus_100\\sample_10.zip'),
    'HACKATHON_REVIEW_300_10_20261005': DatasetMetadata(dataset_id='HACKATHON_REVIEW_300_10_20261005', version=1, type=DatasetType.VALIDATION, pages=19, documents=10, hash='1e77bb5485f8398357bff053a674ec53ed8968262503090a92aef6fb7b5ac9ef', description='Ten-document development draw from hackathon 300 pool; seed 20261305; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_20261005\\corpus_300\\sample_10.zip'),
    'HACKATHON_REVIEW_1000_10_20261005': DatasetMetadata(dataset_id='HACKATHON_REVIEW_1000_10_20261005', version=1, type=DatasetType.VALIDATION, pages=189, documents=10, hash='25dbc63e0dbb6f474261de164f3b45033f3720fa29942f72a098c2cc575181b8', description='Ten-document development draw from hackathon 1000 pool; seed 20262005; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_20261005\\corpus_1000\\sample_10.zip'),
    'HACKATHON_REVIEW_5000_10_20261005': DatasetMetadata(dataset_id='HACKATHON_REVIEW_5000_10_20261005', version=1, type=DatasetType.VALIDATION, pages=17, documents=10, hash='d33250d575558e96cd8b394f36f62f30f95f8e8144bb313bbb6587de33c94804', description='Ten-document development draw from hackathon 5000 pool; seed 20266005; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_20261005\\corpus_5000\\sample_10.zip'),
    'HACKATHON_REVIEW_10000_10_20261005': DatasetMetadata(dataset_id='HACKATHON_REVIEW_10000_10_20261005', version=1, type=DatasetType.VALIDATION, pages=19, documents=10, hash='f5fed3e09e0ecf0ae92c1da64f1fac2dd330880160833b37fbfd85b06babc16e', description='Ten-document development draw from hackathon 10000 pool; seed 20271005; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_20261005\\corpus_10000\\sample_10.zip'),

    # Fixed review draws, 2026-10-05
    'HACKATHON_REVIEW_100_10_2026100502': DatasetMetadata(dataset_id='HACKATHON_REVIEW_100_10_2026100502', version=1, type=DatasetType.VALIDATION, pages=10, documents=10, hash='bf1a1af13289c753eeb84e5cd5e87f2ae805f548b48a6eadba0486958dcea574', description='Ten-document development draw from hackathon 100 pool; seed 2026100602; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_round2_20261005\\corpus_100\\sample_10.zip'),
    'HACKATHON_REVIEW_300_10_2026100502': DatasetMetadata(dataset_id='HACKATHON_REVIEW_300_10_2026100502', version=1, type=DatasetType.VALIDATION, pages=20, documents=10, hash='c4a2cb0765a3fdf52016f8b66c7183973655937c54f92c225bcaaf154b750afd', description='Ten-document development draw from hackathon 300 pool; seed 2026100802; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_round2_20261005\\corpus_300\\sample_10.zip'),
    'HACKATHON_REVIEW_1000_10_2026100502': DatasetMetadata(dataset_id='HACKATHON_REVIEW_1000_10_2026100502', version=1, type=DatasetType.VALIDATION, pages=15, documents=10, hash='a094b820867cc5debb90d499e37a392e0e57efd4125ec557d77530c70d66c4af', description='Ten-document development draw from hackathon 1000 pool; seed 2026101502; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_round2_20261005\\corpus_1000\\sample_10.zip'),
    'HACKATHON_REVIEW_5000_10_2026100502': DatasetMetadata(dataset_id='HACKATHON_REVIEW_5000_10_2026100502', version=1, type=DatasetType.VALIDATION, pages=13, documents=10, hash='60fe7b682b04bc193be17ebfd378e1eecc7001e38e529a584d70fc1a994d89bc', description='Ten-document development draw from hackathon 5000 pool; seed 2026105502; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_round2_20261005\\corpus_5000\\sample_10.zip'),
    'HACKATHON_REVIEW_10000_10_2026100502': DatasetMetadata(dataset_id='HACKATHON_REVIEW_10000_10_2026100502', version=1, type=DatasetType.VALIDATION, pages=14, documents=10, hash='98819fe93ce5a806e7903f7be89092f57a83d80522e21d42c9bfed39f106d4e2', description='Ten-document development draw from hackathon 10000 pool; seed 2026110502; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_round2_20261005\\corpus_10000\\sample_10.zip'),

    # Fixed review draws, 2026-10-05
    'HACKATHON_REVIEW_100_10_2026100503': DatasetMetadata(dataset_id='HACKATHON_REVIEW_100_10_2026100503', version=1, type=DatasetType.VALIDATION, pages=10, documents=10, hash='3331d076c217ada7abfdc61b74a4d146f9cafd71afda55f71eb7fba556401927', description='Ten-document development draw from hackathon 100 pool; seed 2026100603; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_round3_20261005\\corpus_100\\sample_10.zip'),
    'HACKATHON_REVIEW_300_10_2026100503': DatasetMetadata(dataset_id='HACKATHON_REVIEW_300_10_2026100503', version=1, type=DatasetType.VALIDATION, pages=26, documents=10, hash='c2d2a81ca82e8de2ae73acfb585bd7be06c56127c4b286ab2046766a729f9545', description='Ten-document development draw from hackathon 300 pool; seed 2026100803; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_round3_20261005\\corpus_300\\sample_10.zip'),
    'HACKATHON_REVIEW_1000_10_2026100503': DatasetMetadata(dataset_id='HACKATHON_REVIEW_1000_10_2026100503', version=1, type=DatasetType.VALIDATION, pages=15, documents=10, hash='1bb2abda0f1c5d3554ab2467a4d9046217cb23401115f4083f1781bd20939a7c', description='Ten-document development draw from hackathon 1000 pool; seed 2026101503; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_round3_20261005\\corpus_1000\\sample_10.zip'),
    'HACKATHON_REVIEW_5000_10_2026100503': DatasetMetadata(dataset_id='HACKATHON_REVIEW_5000_10_2026100503', version=1, type=DatasetType.VALIDATION, pages=17, documents=10, hash='e3320fc76183390733f2ecb112637ca85edd0ecf004b4c14a535a9318bc81180', description='Ten-document development draw from hackathon 5000 pool; seed 2026105503; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_round3_20261005\\corpus_5000\\sample_10.zip'),
    'HACKATHON_REVIEW_10000_10_2026100503': DatasetMetadata(dataset_id='HACKATHON_REVIEW_10000_10_2026100503', version=1, type=DatasetType.VALIDATION, pages=19, documents=10, hash='1f62d6dbc7faa03c34afe06cc68a3ee65cb899c51275a843f83bdf4b15b2dcd1', description='Ten-document development draw from hackathon 10000 pool; seed 2026110503; not an independent holdout.', source='evaluation_results\\benchmark_review_5x10_round3_20261005\\corpus_10000\\sample_10.zip'),

    # Fixed review draws, 2026-10-05
    'HACKATHON_REVIEW_100_50_2026100601': DatasetMetadata(dataset_id='HACKATHON_REVIEW_100_50_2026100601', version=1, type=DatasetType.VALIDATION, pages=50, documents=50, hash='22bf1b628e279366a43b239081692a5f930b1ec90b14a8a21fcae6a28919c1f9', description='50-document development draw from hackathon 100 pool; seed 2026100701; not an independent holdout.', source='evaluation_results\\benchmark_review_5x50_20261006\\corpus_100\\sample_50.zip'),
    'HACKATHON_REVIEW_300_50_2026100601': DatasetMetadata(dataset_id='HACKATHON_REVIEW_300_50_2026100601', version=1, type=DatasetType.VALIDATION, pages=102, documents=50, hash='2b31ad081b73aeabe3906f50f5da96ab1f105d020d17b4e7f03c7bc68627d42a', description='50-document development draw from hackathon 300 pool; seed 2026100901; not an independent holdout.', source='evaluation_results\\benchmark_review_5x50_20261006\\corpus_300\\sample_50.zip'),
    'HACKATHON_REVIEW_1000_50_2026100601': DatasetMetadata(dataset_id='HACKATHON_REVIEW_1000_50_2026100601', version=1, type=DatasetType.VALIDATION, pages=123, documents=50, hash='48fbea52354392f357cb90d052a9dcc87b2ec1318baa21d38fde90c524fd0920', description='50-document development draw from hackathon 1000 pool; seed 2026101601; not an independent holdout.', source='evaluation_results\\benchmark_review_5x50_20261006\\corpus_1000\\sample_50.zip'),
    'HACKATHON_REVIEW_5000_50_2026100601': DatasetMetadata(dataset_id='HACKATHON_REVIEW_5000_50_2026100601', version=1, type=DatasetType.VALIDATION, pages=145, documents=50, hash='18969c6a0df0520253d46742779ebd694b667ea26c9b9aa79cf2336b6a39d4e0', description='50-document development draw from hackathon 5000 pool; seed 2026105601; not an independent holdout.', source='evaluation_results\\benchmark_review_5x50_20261006\\corpus_5000\\sample_50.zip'),
    'HACKATHON_REVIEW_10000_50_2026100601': DatasetMetadata(dataset_id='HACKATHON_REVIEW_10000_50_2026100601', version=1, type=DatasetType.VALIDATION, pages=82, documents=50, hash='e74fa9bf4651976e61e83789641d4c3678e107604a5208d3c266001735f6932a', description='50-document development draw from hackathon 10000 pool; seed 2026110601; not an independent holdout.', source='evaluation_results\\benchmark_review_5x50_20261006\\corpus_10000\\sample_50.zip'),

    "HACKATHON_10000_FRESH_100_20261007": DatasetMetadata(dataset_id="HACKATHON_10000_FRESH_100_20261007", version=1, type=DatasetType.VALIDATION, pages=188, documents=100, hash="e00f9e82a0e18c64a077ec93fe30c64caee9391de710cb91a52551f5da53e1ab", description='100 source-unique group-stratified documents from full Hackathon 10000; seed 20261007100100; excludes reviewed250; development benchmark, not adjudicated holdout.', source="corpus10000_sample100_v320_20261007/corpus_10000/sample_100.zip"),

    "HACKATHON_10000_FRESH_50_20261008": DatasetMetadata(dataset_id="HACKATHON_10000_FRESH_50_20261008", version=1, type=DatasetType.VALIDATION, pages=91, documents=50, hash="8ee311954c2d1a126b71e142f9df819793b9fa8b74e0bb9e0ec3ecf896fa8bd4", description='50 source-unique group-stratified documents from full Hackathon 10000; seed 20261008100050; excludes reviewed250; development benchmark, not adjudicated holdout.', source="new50_v324_20261008/corpus_10000/sample_50.zip"),

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
