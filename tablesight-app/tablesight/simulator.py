"""Scenario simulator: generates observation streams for edge cases (no video needed)."""
from collections.abc import Callable, Iterator

from .table import Observation

Spec = Callable[[float], tuple[int, int]]  # t -> (guests, staff)


def run(spec: Spec, duration: float, dt: float = 1.0, **obs_kw) -> Iterator[Observation]:
    t = 0.0
    while t <= duration:
        g, s = spec(t)
        yield Observation(t, g, s, **obs_kw)
        t += dt


def seated_party(arrive: float, leave: float, party: int = 2,
                 staff_visits: tuple[tuple[float, float], ...] = ()) -> Spec:
    def spec(t: float) -> tuple[int, int]:
        guests = party if arrive <= t < leave else 0
        staff = 1 if any(a <= t < b for a, b in staff_visits) else 0
        return guests, staff
    return spec


def with_gaps(spec: Spec, gaps: tuple[tuple[float, float], ...]) -> Spec:
    """Guests momentarily vanish (restroom, occlusion, detector dropout)."""
    return lambda t: (0, spec(t)[1]) if any(a <= t < b for a, b in gaps) else spec(t)


def walk_by(at: float, secs: float = 4) -> Spec:
    return lambda t: (1, 0) if at <= t < at + secs else (0, 0)
