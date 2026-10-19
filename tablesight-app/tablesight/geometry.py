"""Floor geometry: zones, point-in-polygon, 4-point homography (pixels -> floor plan metres)."""
from dataclasses import dataclass

Point = tuple[float, float]


def point_in_polygon(p: Point, poly: list[Point]) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            raise ValueError("degenerate calibration points (collinear?)")
        m[c], m[piv] = m[piv], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [v - f * w for v, w in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


@dataclass(frozen=True)
class Homography:
    h: tuple[float, ...]  # 8 params, h33 = 1

    @classmethod
    def from_points(cls, src: list[Point], dst: list[Point]) -> "Homography":
        if len(src) != 4 or len(dst) != 4:
            raise ValueError("need exactly 4 point pairs")
        a, b = [], []
        for (x, y), (u, v) in zip(src, dst):
            a.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
            a.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
        return cls(tuple(_solve(a, b)))

    def apply(self, p: Point) -> Point:
        x, y = p
        h = self.h
        w = h[6] * x + h[7] * y + 1
        return ((h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w)


def foot_point(box: tuple[float, float, float, float]) -> Point:
    """Bottom-centre of an (x1,y1,x2,y2) box: where a person touches the floor.
    Using the box centre would put seated guests' bodies over the wrong table."""
    return ((box[0] + box[2]) / 2, box[3])


@dataclass(frozen=True)
class Zone:
    zone_id: str
    polygon: list[Point]   # floor-plan coordinates
    kind: str = "table"    # table | queue | entrance | exclude (windows, mirrors, street)

    def contains(self, p: Point) -> bool:
        return point_in_polygon(p, self.polygon)


def assign_zone(p: Point, zones: list[Zone]) -> Zone | None:
    """Exclusion zones win (people behind glass, mirrors, outside the window never count)."""
    hit = [z for z in zones if z.contains(p)]
    if any(z.kind == "exclude" for z in hit):
        return None
    return hit[0] if hit else None
