"""YOLOX-S person detector adapter (Detector interface) with tiled inference for small, distant people.

Model: YOLOX-S ONNX from opencv_zoo (code Apache-2.0; COCO-trained weights: provenance NOT yet verified,
see docs/DECISIONS.md D7). Needs opencv (dnn) at runtime; imported lazily so the core stays dependency-free.
Pre/post-processing follows the opencv_zoo reference: RGB letterbox to 640x640 (pad 114), raw 0-255 input,
anchor-free grid decode with strides 8/16/32, class-aware NMS.
"""
from __future__ import annotations

from .perception import RawDet

PERSON = 0


class YoloXPerson:
    def __init__(self, model_path: str, conf: float = 0.35, nms: float = 0.5, tiles: int = 1,
                 overlap: float = 0.2):
        import cv2
        import numpy as np
        self.cv2, self.np = cv2, np
        self.net = cv2.dnn.readNet(model_path)
        self.conf, self.nms, self.tiles, self.overlap = conf, nms, tiles, overlap
        self.size = 640
        strides = [8, 16, 32]
        grids, exp = [], []
        for s in strides:
            n = self.size // s
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            g = np.stack((xv, yv), 2).reshape(1, -1, 2)
            grids.append(g)
            exp.append(np.full((1, g.shape[1], 1), s))
        self.grids, self.strides = np.concatenate(grids, 1), np.concatenate(exp, 1)

    def _infer(self, rgb):
        cv2, np = self.cv2, self.np
        h, w = rgb.shape[:2]
        r = min(self.size / h, self.size / w)
        pad = np.full((self.size, self.size, 3), 114, np.uint8)
        pad[: int(h * r), : int(w * r)] = cv2.resize(rgb, (int(w * r), int(h * r)))
        self.net.setInput(np.transpose(pad, (2, 0, 1))[None].astype(np.float32))
        d = self.net.forward(self.net.getUnconnectedOutLayersNames())[0][0].copy()
        d[:, :2] = (d[:, :2] + self.grids[0]) * self.strides[0]
        d[:, 2:4] = np.exp(d[:, 2:4]) * self.strides[0]
        scores = d[:, 4] * d[:, 5 + PERSON]
        m = scores >= self.conf
        d, scores = d[m], scores[m]
        if not len(d):
            return []
        xywh = np.stack([d[:, 0] - d[:, 2] / 2, d[:, 1] - d[:, 3] / 2, d[:, 2], d[:, 3]], 1) / r
        keep = cv2.dnn.NMSBoxes(xywh.tolist(), scores.tolist(), self.conf, self.nms)
        return [(float(xywh[i, 0]), float(xywh[i, 1]), float(xywh[i, 0] + xywh[i, 2]),
                 float(xywh[i, 1] + xywh[i, 3]), float(scores[i])) for i in np.array(keep).reshape(-1)]

    def detect(self, frame) -> list[RawDet]:
        """frame: BGR ndarray. Tiles run left-to-right with overlap; boxes are merged with NMS."""
        cv2, np = self.cv2, self.np
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        W = rgb.shape[1]
        tw = int(W / (self.tiles - (self.tiles - 1) * self.overlap)) if self.tiles > 1 else W
        step = int(tw * (1 - self.overlap))
        out = []
        for i in range(self.tiles):
            x0 = min(i * step, W - tw)
            for x1, y1, x2, y2, s in self._infer(rgb[:, x0:x0 + tw]):
                out.append((x1 + x0, y1, x2 + x0, y2, s))
        if self.tiles > 1 and out:
            b = [[o[0], o[1], o[2] - o[0], o[3] - o[1]] for o in out]
            keep = cv2.dnn.NMSBoxes(b, [o[4] for o in out], self.conf, self.nms)
            out = [out[i] for i in np.array(keep).reshape(-1)]
        return [RawDet((o[0], o[1], o[2], o[3]), o[4]) for o in out]
