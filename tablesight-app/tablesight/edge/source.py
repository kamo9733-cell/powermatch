"""Frame sources. OpenCV is imported lazily so the agent core runs (and tests run) without it."""
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Frame:
    t: float  # capture time, local clock (correct with clock.ClockSync before sending)
    data: Any  # opaque image (numpy array from OpenCV, or bytes in tests)


class FrameSource(Protocol):
    def open(self) -> bool: ...
    def read(self) -> Frame | None: ...  # None = no frame (end of file or stream fault)
    def close(self) -> None: ...


class OpenCVMissing(RuntimeError):
    pass


def _import_cv2() -> Any:
    try:
        import cv2
    except ImportError as e:  # pragma: no cover - depends on environment
        raise OpenCVMissing("install opencv-python-headless to use RTSP/file sources") from e
    return cv2


class _CvSource:
    """cv2.VideoCapture wrapper. `cv2_loader` is injectable for tests."""

    def __init__(self, target: str, cv2_loader: Callable[[], Any] = _import_cv2,
                 clock: Callable[[], float] = time.time):
        self.target, self._load, self._clock, self._cap = target, cv2_loader, clock, None

    def open(self) -> bool:
        cv2 = self._load()
        self._cap = cv2.VideoCapture(self.target)
        if not self._cap.isOpened():
            self.close()
            return False
        return True

    def read(self) -> Frame | None:
        if self._cap is None:
            return None
        ok, img = self._cap.read()
        return Frame(self._clock(), img) if ok else None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class FileSource(_CvSource):
    pass


class RtspSource(_CvSource):
    def __init__(self, url: str, **kw: Any):
        if not url.lower().startswith(("rtsp://", "rtsps://")):
            raise ValueError("RTSP url must start with rtsp:// or rtsps://")
        super().__init__(url, **kw)

    def __repr__(self) -> str:  # never leak camera credentials into logs
        return "RtspSource(<redacted>)"


class ListSource:
    """Deterministic in-memory source for tests and simulation."""

    def __init__(self, frames: Iterable[Frame]):
        self._frames, self._it, self.opened = list(frames), None, False

    def open(self) -> bool:
        self._it, self.opened = iter(self._frames), True
        return True

    def read(self) -> Frame | None:
        return next(self._it, None) if self._it else None

    def close(self) -> None:
        self.opened = False
