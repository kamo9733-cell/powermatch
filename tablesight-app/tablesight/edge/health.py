"""Heartbeat payload. Matches POST /edge/heartbeat?version=... with the dict as JSON body."""
from dataclasses import dataclass, field


@dataclass
class CameraHealth:
    camera_id: str
    connected: bool = False
    last_frame_t: float | None = None
    fps: float = 0.0
    reconnects: int = 0

    def status(self, now: float, stale_after_s: float = 30.0) -> str:
        if not self.connected:
            return "down"
        if self.last_frame_t is None or now - self.last_frame_t > stale_after_s:
            return "stale"  # connected but frozen/no frames
        return "ok"


@dataclass
class Heartbeat:
    version: str
    cameras: list[CameraHealth] = field(default_factory=list)

    def payload(self, now: float, outbox_depth: int, clock_offset: float | None = None) -> dict:
        cams = {c.camera_id: {"status": c.status(now), "fps": round(c.fps, 2), "reconnects": c.reconnects}
                for c in self.cameras}
        return {"t": now, "outbox_depth": outbox_depth, "clock_offset_s": clock_offset, "cameras": cams,
                "cameras_ok": sum(v["status"] == "ok" for v in cams.values()), "cameras_total": len(cams)}
