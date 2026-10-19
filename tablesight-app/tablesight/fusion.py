"""Multi-camera fusion: dedupe the same person seen by overlapping cameras.

Geometry-only (floor-plan distance), deliberately NO appearance re-ID: see docs/legal/PRIVACY_ANALYSIS.md.
"""
from dataclasses import dataclass

from .geometry import Point


@dataclass(frozen=True)
class Detection:
    cam: str
    pos: Point          # floor-plan metres
    conf: float
    role: str = "guest"


def fuse(dets: list[Detection], radius_m: float = 0.45) -> list[Detection]:
    """Greedy merge of detections from DIFFERENT cameras closer than radius_m.
    Two people from the same camera are never merged (couples stay two people)."""
    out: list[tuple[Detection, set[str]]] = []
    for d in sorted(dets, key=lambda d: -d.conf):
        for i, (k, cams) in enumerate(out):
            dist = ((k.pos[0] - d.pos[0]) ** 2 + (k.pos[1] - d.pos[1]) ** 2) ** 0.5
            if d.cam not in cams and dist <= radius_m:
                cams.add(d.cam)
                break
        else:
            out.append((d, {d.cam}))
    return [k for k, _ in out]
