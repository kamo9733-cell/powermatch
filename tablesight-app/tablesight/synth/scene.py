"""Deterministic (seeded) synthetic scenes for tracker / role evaluation.

Pure python + numpy. Produces, per frame: noisy detector output (box, confidence, torso colour
feature, never a face) and exact ground truth (identity, role, true box). Every scene is
SYNTHETIC: it models a detector's failure modes, it is not footage and says nothing about
real-world accuracy.

Hard cases modelled: crossing paths, staff occluding guests, couples standing close (merged
detections), dim-light noise, detector dropout bursts, false positives (random + static
"poster" ghosts), confidence flicker.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from ..perception import RawDet, iou

Box = tuple[float, float, float, float]
FP_PID = -1       # false positive (no real person)
MERGED_PID = -2   # one detection covering two people


@dataclass(frozen=True)
class SceneConfig:
    name: str = "custom"
    seed: int = 0
    n_frames: int = 300
    fps: float = 10.0
    width: int = 1280
    height: int = 720
    base_det_prob: float = 0.97
    box_jitter: float = 2.0          # px std on each box coordinate
    conf_mean: float = 0.85
    conf_std: float = 0.07
    colour_noise: float = 0.03
    dim: bool = False                # candlelight / dim evening
    burst_start_prob: float = 0.0    # per person per frame: start a detector dropout burst
    burst_len: tuple[int, int] = (3, 12)
    fp_rate: float = 0.0             # expected new false positives per frame
    fp_len: tuple[int, int] = (2, 10)
    static_fps: int = 0              # persistent ghosts (poster / mirror reflection)
    flicker: float = 0.0             # per person per frame: confidence collapses to 0.15-0.45
    merge_iou: float = 1.0           # gt boxes closer than this IoU may fuse into one detection
    merge_prob: float = 0.0


@dataclass(frozen=True)
class SynthDet:
    det: RawDet
    pid: int  # ground-truth person, FP_PID or MERGED_PID


@dataclass(frozen=True)
class GtBox:
    pid: int
    role: str
    box: Box
    occlusion: float  # 0..1 fraction covered by nearer people


@dataclass
class Frame:
    idx: int
    t: float
    dets: list[SynthDet]
    gt: list[GtBox]


@dataclass
class Person:
    pid: int
    role: str
    feat: tuple[float, float, float]
    keys: list[tuple[int, float, float]]  # (frame, foot_x, foot_y)

    def foot(self, f: int) -> tuple[float, float] | None:
        if f < self.keys[0][0] or f > self.keys[-1][0]:
            return None
        fr = [k[0] for k in self.keys]
        return (float(np.interp(f, fr, [k[1] for k in self.keys])),
                float(np.interp(f, fr, [k[2] for k in self.keys])))


@dataclass
class Scene:
    config: SceneConfig
    frames: list[Frame]
    people: list[Person] = field(default_factory=list)
    synthetic: bool = True  # always; carried into exports


def person_box(x: float, foot_y: float) -> Box:
    h = 80 + 0.25 * (foot_y - 250)   # crude perspective: nearer (lower) people are bigger
    w = 0.42 * h
    return (x - w / 2, foot_y - h, x + w / 2, foot_y)


# --- people & scenarios -----------------------------------------------------------------------
def _feat(rng, role: str) -> tuple[float, float, float]:
    if role == "staff":
        return (float(rng.normal(0.62, 0.01)), 0.6, 0.3)
    if rng.random() < 0.2:  # guest in black / navy: looks like the uniform (hard case)
        return (float(rng.normal(0.62, 0.02)), 0.5, 0.3)
    return (float(rng.random()), float(rng.uniform(0.2, 0.8)), float(rng.uniform(0.35, 0.9)))


def _walker(rng, pid, role, f0, f1, n_way=3):
    fr = sorted({f0, f1, *rng.integers(f0, f1, n_way - 1).tolist()}) if f1 > f0 + 3 else [f0, f1]
    keys = [(int(f), float(rng.uniform(120, 1160)), float(rng.uniform(300, 680))) for f in fr]
    return Person(pid, role, _feat(rng, role), keys)


def _people(name: str, rng, n: int) -> list[Person]:
    P = Person
    j = lambda s=15: float(rng.uniform(-s, s))  # noqa: E731
    if name in ("crossing", "dim"):
        a = P(1, "guest", _feat(rng, "guest"), [(10, 200 + j(), 400 + j()), (170, 1000, 560)])
        b = P(2, "guest", _feat(rng, "guest"), [(10, 1000 + j(), 400 + j()), (170, 200, 560)])
        c = P(3, "staff", _feat(rng, "staff"), [(20, 600 + j(40), 300), (200, 600 + j(40), 690)])
        d = P(4, "staff", _feat(rng, "staff"), [(40, 1100, 480 + j()), (230, 150, 500 + j())])
        return [a, b, c, d]
    if name == "staff_occludes_guest":
        g1 = P(1, "guest", _feat(rng, "guest"), [(0, 400 + j(), 400), (n, 404 + j(), 402)])
        g2 = P(2, "guest", _feat(rng, "guest"), [(0, 520 + j(), 420), (n, 516 + j(), 418)])
        g3 = P(3, "guest", _feat(rng, "guest"), [(0, 800 + j(), 410), (n, 796 + j(), 408)])
        s1 = P(4, "staff", _feat(rng, "staff"),
               [(30, 150, 520 + j()), (90, 390, 520), (105, 400, 520), (170, 900, 520 + j())])
        s2 = P(5, "staff", _feat(rng, "staff"),
               [(120, 1000, 540), (190, 810, 540), (200, 800, 540), (280, 300, 560)])
        return [g1, g2, g3, s1, s2]
    if name == "couple":
        w = 0.42 * (80 + 0.25 * 150)  # box width near y=400
        sp = 0.85 * w
        c1 = P(1, "guest", _feat(rng, "guest"), [(10, 150, 450), (200, 1000, 480)])
        c2 = P(2, "guest", _feat(rng, "guest"), [(10, 150 + sp, 450), (200, 1000 + sp, 480)])
        d1 = P(3, "guest", _feat(rng, "guest"), [(0, 800, 560 + j()), (n, 805, 560 + j())])
        d2 = P(4, "guest", _feat(rng, "guest"), [(0, 800 + 0.8 * w, 560 + j()), (n, 805 + 0.8 * w, 560)])
        x = P(5, "staff", _feat(rng, "staff"), [(60, 1100, 470), (250, 250, 500)])
        return [c1, c2, d1, d2, x]
    if name == "busy_night":
        return [_walker(rng, i + 1, "staff" if i < 3 else "guest", 0, n - 1, 5) for i in range(10)]
    # dropout_fp, flicker: wanderers
    return [_walker(rng, i + 1, "staff" if i < 2 else "guest", int(rng.integers(0, 30)),
                    n - 1 - int(rng.integers(0, 30)), 4) for i in range(5)]


SCENARIOS: dict[str, SceneConfig] = {
    "crossing": SceneConfig(name="crossing"),
    "staff_occludes_guest": SceneConfig(name="staff_occludes_guest"),
    "couple": SceneConfig(name="couple", merge_iou=0.12, merge_prob=0.3),
    "dim": SceneConfig(name="dim", dim=True),
    "dropout_fp": SceneConfig(name="dropout_fp", burst_start_prob=0.02, fp_rate=0.4, static_fps=2),
    "flicker": SceneConfig(name="flicker", flicker=0.3),
    "busy_night": SceneConfig(name="busy_night", dim=True, burst_start_prob=0.01, fp_rate=0.2,
                              static_fps=1, flicker=0.1, merge_iou=0.12, merge_prob=0.15),
}


# --- rendering ----------------------------------------------------------------------------------
def _occlusion(boxes: dict[int, Box]) -> dict[int, float]:
    occ = {}
    for a, ba in boxes.items():
        area = max((ba[2] - ba[0]) * (ba[3] - ba[1]), 1e-6)
        m = 0.0
        for b, bb in boxes.items():
            if b != a and bb[3] > ba[3]:  # bb is nearer the camera
                ix = max(0.0, min(ba[2], bb[2]) - max(ba[0], bb[0]))
                iy = max(0.0, min(ba[3], bb[3]) - max(ba[1], bb[1]))
                m = max(m, ix * iy / area)
        occ[a] = m
    return occ


def _clip01(v: float) -> float:
    return float(min(1.0, max(0.0, v)))


def generate(scenario: str | SceneConfig, seed: int | None = None) -> Scene:
    """Same (scenario, seed) always yields the identical Scene."""
    cfg = SCENARIOS[scenario] if isinstance(scenario, str) else scenario
    if seed is not None:
        cfg = replace(cfg, seed=seed)
    rng = np.random.default_rng(cfg.seed)
    people = _people(cfg.name if cfg.name in SCENARIOS else "dropout_fp", rng, cfg.n_frames)
    jit = cfg.box_jitter * (2.5 if cfg.dim else 1.0)
    cnoise = cfg.colour_noise * (3.0 if cfg.dim else 1.0)
    conf_scale = 0.7 if cfg.dim else 1.0
    det_p = cfg.base_det_prob - (0.1 if cfg.dim else 0.0)
    burst = {p.pid: 0 for p in people}
    fps_live: list[dict] = []
    statics = [{"box": person_box(float(rng.uniform(100, 1180)), float(rng.uniform(320, 600))),
                "conf": float(rng.uniform(0.55, 0.8))} for _ in range(cfg.static_fps)]
    frames: list[Frame] = []
    for f in range(cfg.n_frames):
        pos = {p.pid: p.foot(f) for p in people}
        boxes = {pid: person_box(*xy) for pid, xy in pos.items() if xy is not None}
        occ = _occlusion(boxes)
        role = {p.pid: p.role for p in people}
        gt = [GtBox(pid, role[pid], b, occ[pid]) for pid, b in boxes.items()]
        dets: list[SynthDet] = []
        merged: set[int] = set()
        if cfg.merge_prob > 0:
            ids = list(boxes)
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    if (a not in merged and b not in merged and iou(boxes[a], boxes[b]) > cfg.merge_iou
                            and rng.random() < cfg.merge_prob):
                        merged |= {a, b}
                        ba, bb = boxes[a], boxes[b]
                        ub = (min(ba[0], bb[0]), min(ba[1], bb[1]), max(ba[2], bb[2]), max(ba[3], bb[3]))
                        dets.append(SynthDet(RawDet(ub, _clip01(rng.normal(0.7, 0.08)),
                                                    ((0.5, 0.4, 0.4))), MERGED_PID))
        for p in people:
            if p.pid not in boxes or p.pid in merged:
                continue
            if burst[p.pid] > 0:
                burst[p.pid] -= 1
                continue
            if rng.random() < cfg.burst_start_prob:
                burst[p.pid] = int(rng.integers(cfg.burst_len[0], cfg.burst_len[1] + 1))
                continue
            o = occ[p.pid]
            if rng.random() > det_p * (1 - o) ** 1.5:
                continue
            s = jit * (1 + 3 * o)
            b = boxes[p.pid]
            nb = tuple(float(v + rng.normal(0, s)) for v in b)
            conf = _clip01(rng.normal(cfg.conf_mean * conf_scale - 0.35 * o, cfg.conf_std))
            if rng.random() < cfg.flicker:
                conf = float(rng.uniform(0.15, 0.45))
            h, sat, v = p.feat
            if cfg.dim:
                sat, v = sat * 0.6, v * 0.6
            feat = (_clip01((h + rng.normal(0, cnoise)) % 1.0), _clip01(sat + rng.normal(0, cnoise)),
                    _clip01(v + rng.normal(0, cnoise)))
            dets.append(SynthDet(RawDet(nb, conf, feat), p.pid))  # type: ignore[arg-type]
        for _ in range(int(rng.poisson(cfg.fp_rate))):
            n = int(rng.integers(cfg.fp_len[0], cfg.fp_len[1] + 1))
            fps_live.append({"left": n, "box": person_box(float(rng.uniform(100, 1180)),
                                                          float(rng.uniform(320, 680))),
                             "conf": float(rng.uniform(0.3, 0.7))})
        for g in fps_live:
            g["left"] -= 1
            dets.append(SynthDet(RawDet(g["box"], g["conf"], (float(rng.random()), 0.4, 0.5)), FP_PID))
        fps_live = [g for g in fps_live if g["left"] > 0]
        for g in statics:
            if rng.random() < 0.85:
                dets.append(SynthDet(RawDet(g["box"], g["conf"], (0.1, 0.3, 0.6)), FP_PID))
        order = rng.permutation(len(dets))
        dets = [dets[i] for i in order]
        frames.append(Frame(f, f / cfg.fps, dets, gt))
    return Scene(cfg, frames, people)


def describe(scene: Scene) -> dict:
    n_det = sum(len(f.dets) for f in scene.frames)
    n_gt = sum(len(f.gt) for f in scene.frames)
    n_fp = sum(1 for f in scene.frames for d in f.dets if d.pid == FP_PID)
    n_mg = sum(1 for f in scene.frames for d in f.dets if d.pid == MERGED_PID)
    return {"scenario": scene.config.name, "synthetic": True, "frames": len(scene.frames),
            "gt_boxes": n_gt, "detections": n_det, "false_positives": n_fp, "merged": n_mg,
            "mean_dets_per_gt": round(math.nan if not n_gt else (n_det - n_fp) / n_gt, 3)}
