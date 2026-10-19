"""python -m tablesight.labeling {new,validate,summarise,import-corrections}"""
from __future__ import annotations

import argparse
import json
import sys

from .corrections import import_corrections
from .schema import (SOURCES, new_clip, read_jsonl, summarise, validate_record, write_jsonl)


def _from_synth(args) -> dict:
    from ..synth.scene import generate
    sc = generate(args.from_synth, args.seed)
    cfg = sc.config
    clip = new_clip(args.clip_id, "synthetic", "synthetic-cc0", cfg.width, cfg.height, cfg.fps,
                    cfg.n_frames, f"tablesight.synth:{cfg.name}:seed={cfg.seed}",
                    annotator="synthetic-ground-truth", collected_at=args.at, created_at=args.at,
                    consent_scope=["eval", "training"])
    tracks: dict[int, dict] = {}
    for fr in sc.frames:
        for g in fr.gt:
            t = tracks.setdefault(g.pid, {"pid": g.pid, "role": g.role, "boxes": []})
            t["boxes"].append({"f": fr.idx, "box": [round(v, 1) for v in g.box],
                               "occluded": g.occlusion > 0.3})
    clip["tracks"] = list(tracks.values())
    clip["tags"] = ["synthetic", cfg.name]
    return clip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tablesight.labeling",
                                 description="Create / validate / summarise clip annotations")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="write a skeleton clip record (or a synthetic one)")
    n.add_argument("--out", required=True)
    n.add_argument("--clip-id", required=True)
    n.add_argument("--source", choices=sorted(SOURCES), default="internal_capture")
    n.add_argument("--licence", default="internal-owned")
    n.add_argument("--source-ref", default="")
    n.add_argument("--venue-id")
    n.add_argument("--annotator", default="unassigned")
    n.add_argument("--width", type=int, default=1280)
    n.add_argument("--height", type=int, default=720)
    n.add_argument("--fps", type=float, default=10.0)
    n.add_argument("--frames", type=int, default=300)
    n.add_argument("--from-synth", help="scenario name: fill tracks from synthetic ground truth")
    n.add_argument("--seed", type=int, default=0)
    n.add_argument("--at", help="fixed ISO timestamp (reproducible output)")
    n.add_argument("--append", action="store_true")
    v = sub.add_parser("validate", help="exit 1 if any record has errors")
    v.add_argument("files", nargs="+")
    s = sub.add_parser("summarise", help="counts by source/licence/role + training eligibility")
    s.add_argument("files", nargs="+")
    c = sub.add_parser("import-corrections", help="import manager corrections export")
    c.add_argument("--input", required=True)
    c.add_argument("--out", required=True, help="annotations JSONL to append to")
    a = ap.parse_args(argv)

    if a.cmd == "new":
        if a.from_synth:
            clip = _from_synth(a)
        else:
            clip = new_clip(a.clip_id, a.source, a.licence, a.width, a.height, a.fps, a.frames,
                            a.source_ref, a.venue_id, a.annotator, collected_at=a.at,
                            created_at=a.at)
        write_jsonl(a.out, [clip], append=a.append)
        print(f"wrote {a.out} (clip {a.clip_id}); run validate before use")
        return 0
    if a.cmd == "import-corrections":
        try:
            existing = {r.get("correction_id") for r in read_jsonl(a.out)[0]}
        except FileNotFoundError:
            existing = set()
        good, bad = import_corrections(a.input, existing)
        write_jsonl(a.out, good, append=True)
        print(f"imported {len(good)}, rejected {len(bad)}")
        for i, issues in bad:
            for x in issues:
                print(f"  row {i}: {x}", file=sys.stderr)
        return 0
    recs: list[dict] = []
    failed = False
    for f in a.files:
        rs, perrs = read_jsonl(f)
        for e in perrs:
            print(f"{f}: {e}", file=sys.stderr)
            failed = True
        recs += rs
        if a.cmd == "validate":
            for i, r in enumerate(rs, 1):
                for x in validate_record(r):
                    print(f"{f}#{i}: {x}", file=sys.stderr if x.level == "error" else sys.stdout)
                    failed = failed or x.level == "error"
    if a.cmd == "summarise":
        print(json.dumps(summarise(recs), indent=2, sort_keys=True))
        return 1 if failed else 0
    print("INVALID" if failed else f"OK ({len(recs)} records)")
    return 1 if failed else 0
