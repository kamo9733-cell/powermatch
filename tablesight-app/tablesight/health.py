"""Camera health: frozen frame, covered/dark lens, bump (scene shift). Works on cheap frame stats."""
from dataclasses import dataclass, field


@dataclass
class FrameStats:
    t: float
    mean_luma: float      # 0..255
    sharpness: float      # e.g. variance of Laplacian
    signature: tuple[float, ...]  # coarse downsampled grid of luma


@dataclass
class CameraHealth:
    frozen_after_s: float = 10
    dark_luma: float = 12
    blur_sharpness: float = 5
    bump_threshold: float = 40
    _last_change_t: float | None = None
    _last_sig: tuple[float, ...] | None = None
    _baseline: tuple[float, ...] | None = None
    issues: list[str] = field(default_factory=list)

    def update(self, f: FrameStats) -> list[str]:
        issues = []
        if self._last_sig is None or _dist(f.signature, self._last_sig) > 0.01:
            self._last_change_t = f.t
        self._last_sig = f.signature
        if self._last_change_t is not None and f.t - self._last_change_t >= self.frozen_after_s:
            issues.append("frozen")
        if f.mean_luma < self.dark_luma:
            issues.append("covered_or_dark")
        elif f.sharpness < self.blur_sharpness:
            issues.append("blurred_or_dirty_lens")
        if self._baseline is None:
            self._baseline = f.signature
        elif "frozen" not in issues and _dist(f.signature, self._baseline) > self.bump_threshold:
            issues.append("moved_or_bumped")
        self.issues = issues
        return issues

    def rebaseline(self) -> None:
        """Call after an owner confirms the camera was intentionally moved."""
        self._baseline = self._last_sig


def _dist(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / max(len(a), 1)
