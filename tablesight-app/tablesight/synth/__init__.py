"""SYNTHETIC scene generator + tracker metrics. Nothing here is real-world footage or accuracy."""
from .metrics import TrackMetrics, run_tracker, score_tracking
from .scene import SCENARIOS, Frame, GtBox, Scene, SceneConfig, SynthDet, generate

__all__ = ["SCENARIOS", "Frame", "GtBox", "Scene", "SceneConfig", "SynthDet", "TrackMetrics",
           "generate", "run_tracker", "score_tracking"]
