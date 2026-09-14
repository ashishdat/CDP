from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

import pytest
import yaml
from PIL import Image

from datasets.registry import REGISTRY, DatasetManager, DatasetType


def test_registered_development_metadata():
    manager = DatasetManager.load()
    assert manager.metadata.type == DatasetType.DEVELOPMENT
    assert manager.describe()["documents"] == 1000
    assert manager.describe()["pages"] == 2173
    assert "ENGINEERING_BENCHMARK_V1" not in REGISTRY


def test_config_cannot_relabel_dataset(tmp_path):
    manager = DatasetManager.load()
    config = {key: manager.describe()[key] for key in
              ("dataset_id", "root", "pages", "documents", "description")}
    config["pages"] = 1230
    path = tmp_path / "dataset.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="pages"):
        DatasetManager.load(path)
    config["dataset_id"] = "ENGINEERING_BENCHMARK_V1"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown dataset_id"):
        DatasetManager.load(path)


def test_verify_multipage_archive_without_extraction(tmp_path):
    image = Image.new("L", (2, 2))
    payload = BytesIO()
    image.save(payload, format="TIFF", save_all=True, append_images=[image])
    path = tmp_path / "sample.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("folder/", b"")
        archive.writestr("folder/document.001", payload.getvalue())
    original = path.read_bytes()
    metadata = replace(REGISTRY["DEVELOPMENT_DATASET_V1"], pages=2, documents=1,
                       hash=sha256(original).hexdigest())
    manager = DatasetManager(metadata, path)
    assert manager.verify()["verified"]
    assert list(tmp_path.iterdir()) == [path]
    assert path.read_bytes() == original
    assert not DatasetManager(replace(metadata, hash="0" * 64), path).verify()["verified"]
    assert not DatasetManager(replace(metadata, pages=3), path).verify()["verified"]


def test_unreadable_document_does_not_pass(tmp_path):
    path = tmp_path / "invalid.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("invalid.001", b"not an image")
    result = DatasetManager(REGISTRY["DEVELOPMENT_DATASET_V1"], path).verify()
    assert not result["verified"]
    assert result["errors"][0]["file"] == "invalid.001"
