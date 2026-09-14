"""Geometry in source-image pixels; boxes use exclusive right/bottom edges."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    x0: int
    y0: int
    x1: int
    y1: int

    def __post_init__(self):
        if any(type(v) is not int for v in (self.x0, self.y0, self.x1, self.y1)):
            raise ValueError("Box coordinates must be integers")
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("Box must have positive area")

    @property
    def width(self):
        return self.x1 - self.x0

    @property
    def height(self):
        return self.y1 - self.y0

    def intersect(self, other: "Box") -> "Box | None":
        x0, y0 = max(self.x0, other.x0), max(self.y0, other.y0)
        x1, y1 = min(self.x1, other.x1), min(self.y1, other.y1)
        return Box(x0, y0, x1, y1) if x0 < x1 and y0 < y1 else None


@dataclass(frozen=True)
class Registration:
    accepted: bool
    matrix: tuple[tuple[float, float, float], tuple[float, float, float]] | None
    max_error: float | None
    reason: str


@dataclass(frozen=True)
class Alignment:
    box: Box
    accepted: bool
    score: float
    reason: str


@dataclass(frozen=True)
class Component:
    box: Box
    area: int


@dataclass(frozen=True)
class GeometryResult:
    registration: Registration
    safe_cell: Box | None
    aligned_roi: Box | None
    alignment: Alignment | None
    components: tuple[Component, ...]
    text_envelope: Box | None
    refined_roi: Box | None
    reasons: tuple[str, ...]
