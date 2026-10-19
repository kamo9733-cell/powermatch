"""Staff vs guest classification with per-venue adaptation from manager corrections.

Pluggable: a RoleClassifier gets features (not faces) and returns (role, confidence).
Feature here = mean uniform colour of the torso crop (HSV). No face or body-shape biometrics.
"""
from dataclasses import dataclass, field

Feature = tuple[float, float, float]  # h,s,v each 0..1


def _d(a: Feature, b: Feature) -> float:
    dh = min(abs(a[0] - b[0]), 1 - abs(a[0] - b[0]))  # hue wraps
    return (dh * 2) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


@dataclass
class UniformClassifier:
    staff_prototypes: list[Feature] = field(default_factory=list)
    guest_samples: list[Feature] = field(default_factory=list)
    margin: float = 0.02
    min_samples: int = 3

    def correct(self, f: Feature, role: str) -> None:
        """Manager tapped 'that's a waiter' / 'that's a guest'."""
        (self.staff_prototypes if role == "staff" else self.guest_samples).append(f)

    def classify(self, f: Feature) -> tuple[str, float]:
        if len(self.staff_prototypes) < self.min_samples:
            return "unknown", 0.0  # honest: untrained venue never guesses
        ds = min(_d(f, p) for p in self.staff_prototypes)
        dg = min((_d(f, g) for g in self.guest_samples), default=0.25)
        gap = dg - ds
        if abs(gap) < self.margin:
            return "unknown", 0.3   # e.g. guest in black in a black-uniform venue
        role = "staff" if gap > 0 else "guest"
        return role, min(0.99, 0.5 + abs(gap) * 2)
