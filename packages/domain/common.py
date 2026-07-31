"""Shared value objects used across the domain model."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> UUID:
    return uuid4()


class DomainModel(BaseModel):
    """Base class: immutable-by-default, strict extra field handling."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        validate_assignment=True,
        str_strip_whitespace=True,
    )


class BoundingBox(DomainModel):
    """Pixel-space bounding box on a specific rendered page image.

    Coordinates are relative to `image_width`/`image_height` so evidence
    remains reproducible even if a page is re-rendered at a different DPI.
    """

    x0: float = Field(ge=0)
    y0: float = Field(ge=0)
    x1: float = Field(ge=0)
    y1: float = Field(ge=0)
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)

    def normalized(self) -> tuple[float, float, float, float]:
        return (
            self.x0 / self.image_width,
            self.y0 / self.image_height,
            self.x1 / self.image_width,
            self.y1 / self.image_height,
        )


class TenantContext(DomainModel):
    tenant_id: str
    correlation_id: UUID = Field(default_factory=new_id)


class ObjectRef(DomainModel):
    """A pointer into object storage. Kafka payloads carry these, never bytes."""

    bucket: str
    key: str
    content_type: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"
