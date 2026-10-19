"""Occupancy vs licensed capacity (with hysteresis) and section balance suggestions.

Occupancy states: ok < near < at < over. Entering a higher state needs the count to hold for
``confirm_s``; leaving needs it to stay below the exit threshold for ``hold_s``. This keeps a
door-counting flicker at the limit from spamming "over/not over" alerts. This module is an
aid, not a legal record: owners remain responsible for the actual head count.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

LEVELS = ("ok", "near", "at", "over")
BALANCED_NOTE = "Sections are balanced; normal rotation is fine."
UNEVEN_NOTE = ("Uneven load: seating the quietest section first helps coverage "
               "(this is about section load, not people).")


@dataclass(frozen=True)
class CountSample:
    t: float
    count: int
    uncertainty: int = 0          # +/- people the perception layer admits to
    stale: bool = False           # camera offline/frozen: skipped, never guessed


@dataclass(frozen=True)
class CapacityConfig:
    licensed: int
    near_frac: float = 0.9
    hysteresis_frac: float = 0.05     # exit threshold = enter threshold - this x licensed (>=1)
    confirm_s: float = 30.0
    hold_s: float = 120.0
    implausible_factor: float = 3.0   # count above this x licensed is treated as a sensor error

    def __post_init__(self) -> None:
        if self.licensed <= 0:
            raise ValueError("licensed capacity must be positive")
        if not 0 < self.near_frac < 1:
            raise ValueError("near_frac must be in (0, 1)")

    def enter(self, level: str) -> int:
        """Smallest count that enters ``level``."""
        L = self.licensed
        return {"ok": 0, "near": min(math.ceil(self.near_frac * L), L - 1 if L > 1 else 1),
                "at": L, "over": L + 1}[level]

    def exit(self, level: str) -> int:
        """Count must be strictly below this to leave ``level`` downwards."""
        return max(1, self.enter(level) - max(1, round(self.hysteresis_frac * self.licensed)))


def evaluate_capacity(samples: list[CountSample], cfg: CapacityConfig) -> dict:
    """Replay head-count samples; return transitions, final state and data-quality counters.

    Rules: stale, negative or implausible samples are skipped and counted (a skipped sample
    neither raises nor clears a state). Upward moves can jump several levels at once once the
    higher level has been held ``confirm_s`` without interruption (flicker between levels restarts the
    clock, so a count bouncing across the limit is not confirmed - the cost is delayed detection); downward moves step to the highest level whose exit
    threshold is still exceeded, once held ``hold_s``. ``possible_breach`` marks samples where
    count + uncertainty exceeds the licence while the state is not ``over`` - surfaced, but it
    does not itself change state. Same-timestamp samples keep the last one.
    """
    by_t = {}
    for s in sorted(samples, key=lambda s: s.t):
        by_t[s.t] = s
    state = "ok"
    up_since: float | None = None
    up_target = state
    down_since: float | None = None
    transitions: list[dict] = []
    skipped = {"stale": 0, "negative": 0, "implausible": 0}
    possible = 0
    for t, s in by_t.items():
        if s.stale:
            skipped["stale"] += 1
            continue
        if s.count < 0:
            skipped["negative"] += 1
            continue
        if s.count > cfg.implausible_factor * cfg.licensed:
            skipped["implausible"] += 1
            continue
        target = max((lv for lv in LEVELS if s.count >= cfg.enter(lv)), key=LEVELS.index)
        if s.count + s.uncertainty > cfg.licensed and state != "over":
            possible += 1
        cur = LEVELS.index(state)
        if LEVELS.index(target) > cur:
            down_since = None
            if up_since is None or LEVELS.index(target) != LEVELS.index(up_target):
                up_since, up_target = t, target
            if t - up_since >= cfg.confirm_s:
                transitions.append({"t": t, "from": state, "to": target, "count": s.count})
                state, up_since = target, None
            continue
        up_since = None
        # Downward: stay in the current level while count >= its exit threshold.
        if cur > 0 and s.count < cfg.exit(state):
            lower = "ok"   # highest lower level whose exit threshold is still exceeded
            for lv in reversed(LEVELS[:cur]):
                if lv == "ok" or s.count >= cfg.exit(lv):
                    lower = lv
                    break
            down_since = t if down_since is None else down_since
            if t - down_since >= cfg.hold_s:
                transitions.append({"t": t, "from": state, "to": lower, "count": s.count})
                state, down_since = lower, None
        else:
            down_since = None
    return {"state": state, "transitions": transitions, "skipped": skipped,
            "possible_breach_samples": possible, "samples": len(by_t)}


# ---------------------------------------------------------------------------------------------
# Section balance
# ---------------------------------------------------------------------------------------------
def section_loads(sections: dict[str, dict]) -> dict[str, dict]:
    """Per-section load. ``sections[name] = {"servers": int, "tables": {id: {"seats": n,
    "party": n (0 if empty), "needs_attention": bool}}}``.

    load = (open covers + 2 x tables flagged needing attention) / servers. Sections without a
    server are reported as ``unstaffed`` (load None) and excluded from suggestions. Negative or
    inconsistent inputs (party > 2x seats) are counted in ``suspect_tables`` and clipped to
    seats * 2 so one bad reading cannot dominate.
    """
    out = {}
    for name, sec in sections.items():
        servers = int(sec.get("servers", 0))
        covers, flagged, open_t, suspect = 0, 0, 0, 0
        for t in sec.get("tables", {}).values():
            party = max(0, int(t.get("party", 0)))
            cap = max(1, int(t.get("seats", 1)))
            if party > 2 * cap:
                suspect += 1
                party = 2 * cap
            covers += party
            open_t += party > 0
            flagged += bool(t.get("needs_attention")) and party > 0
        load = (covers + 2 * flagged) / servers if servers > 0 else None
        out[name] = {"servers": servers, "open_covers": covers, "open_tables": open_t,
                     "flagged": flagged, "load": load, "unstaffed": servers <= 0,
                     "suspect_tables": suspect}
    return out


def suggest_seating(sections: dict[str, dict], party: int, *, min_gap: float = 3.0) -> dict:
    """Which section should the host seat the next party in?

    Ranks staffed sections that have an empty table with enough seats by current load
    (ties by section name, deterministic). If the busiest and quietest staffed sections differ
    by less than ``min_gap`` covers per server the floor is called balanced and the suggestion is
    only advisory (rotate normally). Framed as load per section: it says nothing about any
    person's performance. A party larger than every empty table returns no suggestion.
    """
    if party <= 0:
        raise ValueError("party must be positive")
    loads = section_loads(sections)
    staffed = {n: v for n, v in loads.items() if not v["unstaffed"]}
    eligible = []
    for name, v in staffed.items():
        free = [t for t in sections[name].get("tables", {}).values()
                if int(t.get("party", 0)) <= 0 and int(t.get("seats", 0)) >= party]
        if free:
            eligible.append((v["load"], name))
    notes = []
    unstaffed = sorted(n for n, v in loads.items() if v["unstaffed"])
    if unstaffed:
        notes.append("Unstaffed sections not used: " + ", ".join(unstaffed))
    if not eligible:
        return {"suggestion": None, "balanced": None, "ranking": [], "notes":
                notes + ["no staffed section has an empty table that fits this party"]}
    eligible.sort()
    spread = (max(v["load"] for v in staffed.values()) - min(v["load"] for v in staffed.values()))
    balanced = spread < min_gap
    return {"suggestion": eligible[0][1], "balanced": balanced,
            "ranking": [(n, ld) for ld, n in eligible], "spread": spread,
            "notes": notes + [BALANCED_NOTE if balanced else UNEVEN_NOTE]}


def rebalance_hint(sections: dict[str, dict], *, min_gap: float = 4.0) -> dict | None:
    """If one staffed section's load exceeds another's by ``min_gap``+ per server, suggest
    that a floater/runner help the heavy section. Returns None when balanced or fewer than two
    staffed sections. Team-level wording only."""
    loads = {n: v for n, v in section_loads(sections).items() if not v["unstaffed"]}
    if len(loads) < 2:
        return None
    hi = max(loads, key=lambda n: (loads[n]["load"], n))
    lo = min(loads, key=lambda n: (loads[n]["load"], n))
    gap = loads[hi]["load"] - loads[lo]["load"]
    if gap < min_gap:
        return None
    return {"heavy": hi, "light": lo, "gap": gap,
            "message": f"Section {hi} is carrying more than {lo}; consider extra coverage there."}
