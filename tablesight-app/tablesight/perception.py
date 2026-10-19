"""Perception interfaces + a dependency-free IoU tracker baseline.

Detector is pluggable (RF-DETR / RT-DETR / YOLOX behind this interface; see docs/DECISIONS.md D2).
"""
from dataclasses import dataclass
from typing import Protocol

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class RawDet:
    box: Box
    conf: float


class Detector(Protocol):
    def detect(self, frame) -> list[RawDet]: ...


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


@dataclass
class _Track:
    tid: int
    box: Box
    missed: int = 0
    hits: int = 1


class IouTracker:
    """Greedy IoU association with max_age coasting. Baseline only; swap for ByteTrack later."""

    def __init__(self, iou_min: float = 0.3, max_age: int = 15, min_hits: int = 3):
        self.iou_min, self.max_age, self.min_hits = iou_min, max_age, min_hits
        self._tracks: list[_Track] = []
        self._next = 1

    def update(self, dets: list[RawDet]) -> list[tuple[int, Box]]:
        pairs = sorted(((iou(t.box, d.box), ti, di) for ti, t in enumerate(self._tracks)
                        for di, d in enumerate(dets)), reverse=True)
        used_t, used_d = set(), set()
        for s, ti, di in pairs:
            if s < self.iou_min:
                break
            if ti in used_t or di in used_d:
                continue
            t = self._tracks[ti]
            t.box, t.missed, t.hits = dets[di].box, 0, t.hits + 1
            used_t.add(ti); used_d.add(di)
        for ti, t in enumerate(self._tracks):
            if ti not in used_t:
                t.missed += 1
        for di, d in enumerate(dets):
            if di not in used_d:
                self._tracks.append(_Track(self._next, d.box)); self._next += 1
        self._tracks = [t for t in self._tracks if t.missed <= self.max_age]
        return [(t.tid, t.box) for t in self._tracks if t.missed == 0 and t.hits >= self.min_hits]
