"""JSONL annotation schema (v1) with data lineage, plus validators and a summary.

One JSON object per line. Two record types:

``clip``        an annotated eval/training clip: camera info, per-person tracks (box per frame,
                role staff|guest|unknown) and a ``lineage`` block that answers "where did this
                come from, may we use it commercially, did anyone consent, may we train on it".
``correction``  a manager tap ("that's a waiter") imported from the platform; see corrections.py.

Rules enforced (see CLAUDE.md 2.1, 2.2, 5.2): no non-commercial or unknown licences, no covert
capture, customer data only with recorded consent, training use needs an explicit ``training``
consent scope (default off), and nothing involving minors is training-eligible.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1
SOURCES = {"synthetic", "public_dataset", "internal_capture", "customer"}
ROLES = {"staff", "guest", "unknown"}
SCOPES = {"eval", "training"}
# Licences cleared for commercial closed-source SaaS use. Anything else is rejected until a human
# reviews it and adds it here (and to docs/DATA.md).
COMMERCIAL_OK = {"CC0-1.0", "CC-BY-4.0", "CC-BY-3.0", "Apache-2.0", "MIT", "BSD-2-Clause",
                 "BSD-3-Clause", "synthetic-cc0", "internal-owned", "customer-consent-agreement"}
NON_COMMERCIAL = re.compile(r"(?:^|[-_])NC(?:[-_]|$)|non-?commercial|research-only", re.IGNORECASE)


@dataclass(frozen=True)
class Issue:
    level: str  # "error" | "warning"
    path: str
    msg: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.path}: {self.msg}"


def _iso(v) -> bool:
    try:
        datetime.fromisoformat(str(v))
        return True
    except ValueError:
        return False


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def new_clip(clip_id: str, source: str, licence: str, width: int, height: int, fps: float,
             n_frames: int, source_ref: str = "", venue_id: str | None = None,
             annotator: str = "unassigned", consent_scope: list[str] | None = None,
             collected_at: str | None = None, created_at: str | None = None) -> dict:
    """Skeleton clip record. Consent defaults to NOT obtained / eval-only-unset (safe default)."""
    now = created_at or datetime.now().astimezone().isoformat(timespec="seconds")
    synthetic = source == "synthetic"
    return {
        "record_type": "clip", "schema_version": SCHEMA_VERSION, "clip_id": clip_id,
        "lineage": {
            "source": source, "source_ref": source_ref, "licence": licence,
            "collected_at": collected_at or now, "synthetic": synthetic,
            "covert_capture": False, "contains_minors": False, "faces_blurred": False,
            "consent": {"obtained": synthetic, "scope": list(consent_scope or []),
                        "recorded_at": None, "evidence_ref": None},
        },
        "venue_id": venue_id, "camera": {"width": width, "height": height, "fps": fps},
        "n_frames": n_frames, "annotator": annotator, "created_at": now,
        "tracks": [], "tags": [],
    }


def _validate_lineage(lin, out: list[Issue]) -> dict:
    p = "lineage"
    if not isinstance(lin, dict):
        out.append(Issue("error", p, "missing or not an object"))
        return {}
    src = lin.get("source")
    if src not in SOURCES:
        out.append(Issue("error", f"{p}.source", f"must be one of {sorted(SOURCES)}"))
    lic = lin.get("licence")
    if not isinstance(lic, str) or not lic:
        out.append(Issue("error", f"{p}.licence", "required"))
    elif NON_COMMERCIAL.search(lic):
        out.append(Issue("error", f"{p}.licence", f"{lic!r} blocks commercial use"))
    elif lic not in COMMERCIAL_OK:
        out.append(Issue("error", f"{p}.licence",
                         f"{lic!r} is not on the reviewed commercial-OK list"))
    if not _iso(lin.get("collected_at")):
        out.append(Issue("error", f"{p}.collected_at", "ISO-8601 timestamp required"))
    if lin.get("covert_capture") is not False:
        out.append(Issue("error", f"{p}.covert_capture",
                         "must be present and false; covertly captured footage is never accepted"))
    if not isinstance(lin.get("contains_minors"), bool):
        out.append(Issue("error", f"{p}.contains_minors", "boolean required"))
    if src == "synthetic" and lin.get("synthetic") is not True:
        out.append(Issue("error", f"{p}.synthetic", "synthetic source must set synthetic=true"))
    if src != "synthetic" and lin.get("synthetic") is True:
        out.append(Issue("error", f"{p}.synthetic", "synthetic=true but source is not synthetic"))
    c = lin.get("consent")
    if not isinstance(c, dict):
        out.append(Issue("error", f"{p}.consent", "object required"))
        return lin
    scope = c.get("scope")
    if not isinstance(scope, list) or not set(scope) <= SCOPES:
        out.append(Issue("error", f"{p}.consent.scope", f"list drawn from {sorted(SCOPES)}"))
        scope = []
    if not isinstance(c.get("obtained"), bool):
        out.append(Issue("error", f"{p}.consent.obtained", "boolean required"))
    if src in ("customer", "internal_capture") and not c.get("obtained"):
        out.append(Issue("error", f"{p}.consent.obtained",
                         f"{src} footage needs recorded consent"))
    if "training" in scope:
        if not c.get("obtained"):
            out.append(Issue("error", f"{p}.consent", "training scope without consent"))
        if src != "synthetic":
            if not _iso(c.get("recorded_at")):
                out.append(Issue("error", f"{p}.consent.recorded_at",
                                 "training consent needs a timestamp"))
            if not c.get("evidence_ref"):
                out.append(Issue("error", f"{p}.consent.evidence_ref",
                                 "training consent needs an evidence reference"))
        if lin.get("contains_minors") is True:
            out.append(Issue("error", f"{p}.consent.scope",
                             "clips containing minors are never training-eligible"))
    if src in ("customer", "internal_capture") and lin.get("faces_blurred") is not True:
        out.append(Issue("warning", f"{p}.faces_blurred", "faces not blurred in stored clip"))
    return lin


def _validate_clip(r: dict, out: list[Issue]) -> None:
    _validate_lineage(r.get("lineage"), out)
    cam = r.get("camera")
    w = h = None
    if (not isinstance(cam, dict) or not all(_num(cam.get(k)) and cam[k] > 0
                                             for k in ("width", "height", "fps"))):
        out.append(Issue("error", "camera", "width, height, fps must be positive numbers"))
    else:
        w, h = cam["width"], cam["height"]
    n = r.get("n_frames")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        out.append(Issue("error", "n_frames", "positive integer required"))
        n = None
    if not isinstance(r.get("annotator"), str) or not r.get("annotator"):
        out.append(Issue("error", "annotator", "required"))
    if not _iso(r.get("created_at")):
        out.append(Issue("error", "created_at", "ISO-8601 timestamp required"))
    if not isinstance(r.get("tags"), list):
        out.append(Issue("error", "tags", "list required"))
    tracks = r.get("tracks")
    if not isinstance(tracks, list):
        out.append(Issue("error", "tracks", "list required"))
        return
    seen: set = set()
    for i, t in enumerate(tracks):
        p = f"tracks[{i}]"
        if not isinstance(t, dict):
            out.append(Issue("error", p, "object required"))
            continue
        pid = t.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool):
            out.append(Issue("error", f"{p}.pid", "integer required"))
        elif pid in seen:
            out.append(Issue("error", f"{p}.pid", f"duplicate pid {pid}"))
        seen.add(pid)
        if t.get("role") not in ROLES:
            out.append(Issue("error", f"{p}.role", f"must be one of {sorted(ROLES)}"))
        last = -1
        for k, b in enumerate(t.get("boxes") or []):
            q = f"{p}.boxes[{k}]"
            f, bx = (b.get("f"), b.get("box")) if isinstance(b, dict) else (None, None)
            if not isinstance(f, int) or isinstance(f, bool):
                out.append(Issue("error", f"{q}.f", "integer frame index required"))
                continue
            if n is not None and not 0 <= f < n:
                out.append(Issue("error", f"{q}.f", f"frame {f} outside 0..{n - 1}"))
            if f <= last:
                out.append(Issue("error", f"{q}.f", "frames must be strictly increasing"))
            last = f
            if not (isinstance(bx, list) and len(bx) == 4 and all(_num(v) for v in bx)):
                out.append(Issue("error", f"{q}.box", "[x1,y1,x2,y2] numbers required"))
                continue
            if bx[2] <= bx[0] or bx[3] <= bx[1]:
                out.append(Issue("error", f"{q}.box", "degenerate box (x2<=x1 or y2<=y1)"))
            elif w is not None and (bx[2] <= 0 or bx[3] <= 0 or bx[0] >= w or bx[1] >= h):
                out.append(Issue("error", f"{q}.box", "box entirely outside the frame"))


def validate_record(r) -> list[Issue]:
    out: list[Issue] = []
    if not isinstance(r, dict):
        return [Issue("error", "$", "record must be a JSON object")]
    if r.get("schema_version") != SCHEMA_VERSION:
        out.append(Issue("error", "schema_version", f"must be {SCHEMA_VERSION}"))
    rt = r.get("record_type")
    if rt == "clip":
        if not isinstance(r.get("clip_id"), str) or not r.get("clip_id"):
            out.append(Issue("error", "clip_id", "required"))
        _validate_clip(r, out)
    elif rt == "correction":
        from .corrections import validate_correction
        validate_correction(r, out)
    else:
        out.append(Issue("error", "record_type", "must be 'clip' or 'correction'"))
    return out


def training_eligible(r: dict) -> bool:
    """Valid, consented for training, and no minors. Synthetic data is always eligible."""
    if any(i.level == "error" for i in validate_record(r)):
        return False
    scope = ((r.get("lineage") or {}).get("consent") or {}).get("scope") or []
    if r.get("record_type") == "correction":
        return bool((r.get("consent") or {}).get("training"))
    return "training" in scope or (r["lineage"].get("source") == "synthetic")


def read_jsonl(path: str | Path) -> tuple[list[dict], list[Issue]]:
    recs, errs = [], []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError as e:
            errs.append(Issue("error", f"line {n}", f"invalid JSON: {e.msg}"))
    return recs, errs


def write_jsonl(path: str | Path, recs: list[dict], append: bool = False) -> None:
    with open(path, "a" if append else "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in recs)


def summarise(recs: list[dict]) -> dict:
    clips = [r for r in recs if isinstance(r, dict) and r.get("record_type") == "clip"]
    cors = [r for r in recs if isinstance(r, dict) and r.get("record_type") == "correction"]
    roles: Counter = Counter()
    boxes = 0
    for c in clips:
        for t in c.get("tracks") or []:
            roles[t.get("role")] += 1
            boxes += len(t.get("boxes") or [])
    lin = [c.get("lineage") or {} for c in clips]
    return {
        "records": len(recs), "clips": len(clips), "corrections": len(cors),
        "frames": sum(c.get("n_frames") or 0 for c in clips), "boxes": boxes,
        "tracks_by_role": dict(roles),
        "by_source": dict(Counter(x.get("source") for x in lin)),
        "by_licence": dict(Counter(x.get("licence") for x in lin)),
        "synthetic_clips": sum(1 for x in lin if x.get("synthetic")),
        "training_eligible": sum(1 for r in recs if training_eligible(r)),
        "invalid": sum(1 for r in recs if any(i.level == "error" for i in validate_record(r))),
        "correction_kinds": dict(Counter(c.get("kind") for c in cors)),
    }
