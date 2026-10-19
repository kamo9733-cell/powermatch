"""Perception interfaces + dependency-free trackers.

Detector is pluggable (RF-DETR / RT-DETR / YOLOX behind this interface; see docs/DECISIONS.md D2).
Trackers share one interface: ``update(list[RawDet]) -> list[(track_id, box)]``.

* ``IouTracker``  - the original greedy-IoU baseline (kept unchanged as the comparison point).
* ``ByteTracker`` - two-stage association in the spirit of ByteTrack (Zhang et al., 2021; MIT):
  high-confidence detections first, then low-confidence ones rescue tracks that would otherwise be
  lost. Written from the idea, no code copied. Adds constant-velocity prediction, optimal
  (Hungarian) assignment and an optional torso-colour cue (never faces / body shape).
"""
from dataclasses import dataclass
from typing import Protocol

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class RawDet:
    box: Box
    conf: float
    feat: tuple[float, ...] | None = None  # optional torso colour (h,s,v); appearance cue only


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


# --------------------------------------------------------------------------------------------
# ByteTrack-style tracker
# --------------------------------------------------------------------------------------------
def hungarian(cost: list[list[float]]) -> list[tuple[int, int]]:
    """Minimum-cost assignment on a rectangular matrix (shortest augmenting paths, O(n^2 m))."""
    n = len(cost)
    m = len(cost[0]) if n else 0
    if n == 0 or m == 0:
        return []
    transpose = n > m
    if transpose:
        cost = [list(r) for r in zip(*cost)]
        n, m = m, n
    inf = float("inf")
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    out = [(p[j] - 1, j - 1) for j in range(1, m + 1) if p[j]]
    return [(c, r) for r, c in out] if transpose else out


def _cxcywh(b: Box) -> list[float]:
    return [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2, b[2] - b[0], b[3] - b[1]]


def _box(s: list[float]) -> Box:
    w, h = max(s[2], 1e-3), max(s[3], 1e-3)
    return (s[0] - w / 2, s[1] - h / 2, s[0] + w / 2, s[1] + h / 2)


def _fdist(a, b) -> float:
    """Colour distance 0..~1 between two (h,s,v) features; hue wraps."""
    dh = min(abs(a[0] - b[0]), 1 - abs(a[0] - b[0])) * 2
    return min(1.0, ((dh * dh + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) / 3) ** 0.5 * 2)


@dataclass
class _BTrack:
    tid: int
    s: list[float]            # cx, cy, w, h
    v: list[float]            # velocity of cx, cy (px/frame)
    feat: tuple[float, ...] | None
    hits: int = 1
    missed: int = 0
    age: int = 0
    confirmed: bool = False

    def predicted(self) -> Box:
        return _box([self.s[0] + self.v[0], self.s[1] + self.v[1], self.s[2], self.s[3]])


class ByteTracker:
    """Two-stage association + constant-velocity prediction.

    Stage 1: detections with conf >= high_thresh vs every live track (predicted boxes), cost =
    (1 - IoU) blended with colour distance when both sides carry a feature.
    Stage 2: remaining *low*-confidence detections (low_thresh <= conf < high_thresh) vs tracks
    still unmatched, IoU only: a blurry/occluded person keeps their id instead of fragmenting.
    New tracks are only born from high-confidence detections that no track claimed. Coasting
    tracks are not emitted (same contract as IouTracker) but keep their id for ``max_age`` frames.
    """

    def __init__(self, iou_min: float = 0.2, iou_min_low: float = 0.3, max_age: int = 30,
                 min_hits: int = 3, high_thresh: float = 0.5, low_thresh: float = 0.1,
                 alpha: float = 0.6, beta: float = 0.25, appearance_weight: float = 0.3,
                 vel_decay: float = 0.9):
        self.iou_min, self.iou_min_low = iou_min, iou_min_low
        self.max_age, self.min_hits = max_age, min_hits
        self.high, self.low = high_thresh, low_thresh
        self.alpha, self.beta, self.aw, self.vel_decay = alpha, beta, appearance_weight, vel_decay
        self._tracks: list[_BTrack] = []
        self._next = 1

    # -- association -----------------------------------------------------------------------
    def _match(self, tracks, dets, min_iou, use_app):
        if not tracks or not dets:
            return [], list(range(len(tracks))), list(range(len(dets)))
        big = 1e3
        cost = []
        for t in tracks:
            pb = t.predicted()
            row = []
            for d in dets:
                ov = iou(pb, d.box)
                if ov < min_iou:
                    row.append(big)
                    continue
                c = 1.0 - ov
                if use_app and t.feat is not None and d.feat is not None:
                    c = (1 - self.aw) * c + self.aw * _fdist(t.feat, d.feat)
                row.append(c)
            cost.append(row)
        pairs = [(i, j) for i, j in hungarian(cost) if cost[i][j] < big]
        mt = {i for i, _ in pairs}
        md = {j for _, j in pairs}
        return (pairs, [i for i in range(len(tracks)) if i not in mt],
                [j for j in range(len(dets)) if j not in md])

    def _apply(self, t: _BTrack, d: RawDet) -> None:
        m = _cxcywh(d.box)
        px, py = t.s[0] + t.v[0], t.s[1] + t.v[1]
        rx, ry = m[0] - px, m[1] - py
        t.s = [px + self.alpha * rx, py + self.alpha * ry,
               t.s[2] + 0.5 * (m[2] - t.s[2]), t.s[3] + 0.5 * (m[3] - t.s[3])]
        t.v = [t.v[0] + self.beta * rx, t.v[1] + self.beta * ry]
        if d.feat is not None:
            t.feat = d.feat if t.feat is None else tuple(
                0.8 * a + 0.2 * b for a, b in zip(t.feat, d.feat))
        t.hits += 1
        t.missed = 0
        t.confirmed = t.confirmed or t.hits >= self.min_hits
        self._last[t.tid] = d.box

    def update(self, dets: list[RawDet]) -> list[tuple[int, Box]]:
        self._last: dict[int, Box] = {}
        high = [d for d in dets if d.conf >= self.high]
        low = [d for d in dets if self.low <= d.conf < self.high]
        for t in self._tracks:
            t.age += 1
        pool = self._tracks
        m1, un_t, un_h = self._match(pool, high, self.iou_min, True)
        for ti, di in m1:
            self._apply(pool[ti], high[di])
        rest = [pool[i] for i in un_t]
        # stage 2: low-confidence detections rescue tracks that were seen recently
        recent = [t for t in rest if t.missed <= 2]
        m2, _, _ = self._match(recent, low, self.iou_min_low, False)
        for ti, di in m2:
            self._apply(recent[ti], low[di])
        rescued = {id(recent[i]) for i, _ in m2}
        lost = [t for t in rest if id(t) not in rescued]
        for t in lost:
            t.missed += 1
            t.v = [t.v[0] * self.vel_decay, t.v[1] * self.vel_decay]
            t.s = [t.s[0] + t.v[0], t.s[1] + t.v[1], t.s[2], t.s[3]]
        for j in un_h:
            d = high[j]
            self._tracks.append(_BTrack(self._next, _cxcywh(d.box), [0.0, 0.0], d.feat,
                                        confirmed=self.min_hits <= 1))
            self._last[self._next] = d.box
            self._next += 1
        # unconfirmed tracks die on their first miss; confirmed ones coast up to max_age
        self._tracks = [t for t in self._tracks
                        if t.missed <= (self.max_age if t.confirmed else 1)]
        return [(t.tid, self._last[t.tid]) for t in self._tracks
                if t.missed == 0 and t.confirmed and t.tid in self._last]
