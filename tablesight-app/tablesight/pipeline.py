"""Hero loop glue: detections -> tracks -> floor positions -> zones -> table observations -> events."""
from dataclasses import dataclass, field

from .geometry import Homography, Zone, assign_zone, foot_point
from .perception import IouTracker, RawDet
from .roles import Feature, UniformClassifier
from .table import Event, Observation, Table
from .templates import VenueTemplate


@dataclass
class FloorPipeline:
    tpl: VenueTemplate
    homography: Homography
    zones: list[Zone]
    roles: UniformClassifier
    tracker: IouTracker = field(default_factory=lambda: IouTracker(min_hits=3))
    tables: dict[str, Table] = field(default_factory=dict)
    # role is smoothed per track: one noisy frame must not flip staff<->guest
    _role_votes: dict[int, dict[str, int]] = field(default_factory=dict)

    def __post_init__(self):
        for z in self.zones:
            if z.kind == "table":
                self.tables[z.zone_id] = Table(z.zone_id, self.tpl)

    def _role(self, tid: int, feat: Feature) -> str:
        r, conf = self.roles.classify(feat)
        v = self._role_votes.setdefault(tid, {})
        if r != "unknown" and conf >= 0.5:
            v[r] = v.get(r, 0) + 1
        return max(v, key=v.get) if v else "unknown"

    def step(self, t: float, dets: list[tuple[RawDet, Feature]], stale: bool = False) -> list[Event]:
        before = {k: len(tb.events) for k, tb in self.tables.items()}
        feats = {d.box: f for d, f in dets}
        tracks = self.tracker.update([d for d, _ in dets])
        counts = {k: [0, 0] for k in self.tables}
        unknown_in_zone = {k: 0 for k in self.tables}
        for tid, box in tracks:
            z = assign_zone(self.homography.apply(foot_point(box)), self.zones)
            if not z or z.zone_id not in self.tables:
                continue
            role = self._role(tid, feats.get(box, (0, 0, 0)))
            if role == "staff":
                counts[z.zone_id][1] += 1
            elif role == "guest":
                counts[z.zone_id][0] += 1
            else:
                unknown_in_zone[z.zone_id] += 1
        for k, tb in self.tables.items():
            # unknown-role people lower confidence rather than being guessed as guests
            conf = 0.4 if unknown_in_zone[k] and not counts[k][0] else 1.0
            tb.step(Observation(t, counts[k][0], counts[k][1], conf, stale))
        sec = {z.zone_id: z.section for z in self.zones}
        return [Event(e.t, e.table, e.kind, {**e.detail, **({"section": sec[k]} if sec.get(k) else {})})
                for k, tb in self.tables.items() for e in tb.events[before[k]:]]
