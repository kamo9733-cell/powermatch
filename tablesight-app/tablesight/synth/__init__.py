"""SYNTHETIC scene generator + tracker metrics. Nothing here is real-world footage or accuracy."""
from .metrics import TrackMetrics, evaluate, run_tracker, score_tracking
from .scene import SCENARIOS, Frame, GtBox, Scene, SceneConfig, SynthDet, generate

__all__ = ["SCENARIOS", "Frame", "GtBox", "Scene", "SceneConfig", "SynthDet", "TrackMetrics",
           "evaluate", "generate", "run_tracker", "score_tracking"]
