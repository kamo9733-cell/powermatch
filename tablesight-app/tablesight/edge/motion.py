"""Motion gating + adaptive FPS. Idle cameras are sampled slowly and never reach the detector.

Frames are compared as flat 8-bit grayscale buffers (bytes/bytearray/memoryview), subsampled by
`stride`; with OpenCV, pass `cv2.cvtColor(...).tobytes()` or a numpy uint8 array (buffer protocol).
No numpy dependency.
"""
from dataclasses import dataclass


class MotionGate:
    def __init__(self, threshold: float = 4.0, stride: int = 16):
        self.threshold, self.stride, self._prev = threshold, max(1, stride), None

    def score(self, gray) -> float:
        cur = bytes(memoryview(gray).cast("B")[:: self.stride])
        prev, self._prev = self._prev, cur
        if prev is None or len(prev) != len(cur) or not cur:
            return 0.0 if prev is None else 255.0  # resolution change counts as big change
        return sum(abs(a - b) for a, b in zip(cur, prev, strict=True)) / len(cur)

    def moving(self, gray) -> bool:
        return self.score(gray) >= self.threshold


@dataclass
class FpsPolicy:
    idle_fps: float = 0.2     # one look every 5 s while nothing happens
    active_fps: float = 5.0
    hold_s: float = 10.0      # stay active this long after last motion
    ramp: float = 2.0         # decay factor per step after hold expires


class AdaptiveFps:
    """Feed it motion observations; ask it how long to sleep before the next grab."""

    def __init__(self, policy: FpsPolicy | None = None):
        self.p = policy or FpsPolicy()
        self.fps = self.p.idle_fps
        self._last_motion: float | None = None

    def observe(self, moving: bool, now: float) -> float:
        p = self.p
        if moving:
            self._last_motion, self.fps = now, p.active_fps
        elif self._last_motion is None or now - self._last_motion > p.hold_s:
            self.fps = max(p.idle_fps, self.fps / p.ramp)
        return self.fps

    @property
    def interval_s(self) -> float:
        return 1.0 / self.fps

    @staticmethod
    def should_detect(moving: bool, active: bool) -> bool:
        """Run the expensive detector only when moving or still inside the hold window."""
        return moving or active

    @property
    def active(self) -> bool:
        return self.fps > self.p.idle_fps
