"""Split the boundary line files into 30 x 30 degree cells.

web/geo/{coast,admin0,admin1}.json are each one MultiLineString. The map used to
download all three whole (about 2.3 MB compressed) before drawing a line. Cut into
cells, a visitor loads only the cells under the view and fetches the rest when
they pan or zoom out. Lines are clipped at the cell edges, so a cell never
repeats a line that belongs to its neighbour (no doubled, darker strokes).

Writes web/geo/tiles/<layer>/<cx>-<cy>.json (cx 0..11 from 180W, cy 0..5 from 90S)
and web/geo/tiles/index.json listing the non-empty cells of each layer.
The originals are left alone: the page falls back to them if the index is missing.

    python3 pipeline/split_geo.py
"""
import json
import math
from pathlib import Path

GEO = Path(__file__).resolve().parent.parent / "web" / "geo"
CELL = 30
LAYERS = ["coast", "coastlow", "admin0", "admin1"]

# coastlow is the coast thinned for the zoomed-out map (below zoom LOW_COAST_ZOOM in
# web/index.html). The 10m coast has every fjord and skerry, which at world scale
# piles up into a black smear along Norway, Chile, Alaska. Douglas-Peucker with
# this tolerance (degrees; 0.15 is about 17 km, a few pixels at zoom 4), runs
# shorter than MIN_RUN degrees dropped, and one Chaikin pass to round the corners.
COAST_TOLERANCE = 0.15
MIN_RUN = 0.8


def douglas_peucker(pts, eps):
    """Iterative Douglas-Peucker on a polyline of [x, y]."""
    n = len(pts)
    if n < 3:
        return pts
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    e2 = eps * eps
    while stack:
        i, j = stack.pop()
        ax, ay = pts[i]; bx, by = pts[j]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        far, fd = -1, e2
        for k in range(i + 1, j):
            px, py = pts[k]
            if L2 == 0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
                d = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d > fd:
                far, fd = k, d
        if far >= 0:
            keep[far] = True
            stack.append((i, far)); stack.append((far, j))
    return [p for p, k in zip(pts, keep) if k]


def chaikin(pts):
    """One corner-cutting pass; the ends stay put (so cell clipping still meets)."""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        out.append([0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]])
        out.append([0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]])
    out.append(pts[-1])
    return out


def thin_coast(lines):
    out = []
    for line in lines:
        xs = [p[0] for p in line]; ys = [p[1] for p in line]
        if max(max(xs) - min(xs), max(ys) - min(ys)) < MIN_RUN:
            continue                     # a skerry: gone at this scale
        out.append(chaikin(douglas_peucker(line, COAST_TOLERANCE)))
    return out


def clip_segment(a, b, x0, y0, x1, y1):
    """Liang-Barsky: the part of segment a-b inside the box, or None."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if p == 0:
            if q < 0:
                return None
        else:
            r = q / p
            if p < 0:
                if r > t1: return None
                t0 = max(t0, r)
            else:
                if r < t0: return None
                t1 = min(t1, r)
    return ([a[0] + t0 * dx, a[1] + t0 * dy], [a[0] + t1 * dx, a[1] + t1 * dy])


def clip_line(line, box):
    """Pieces of a polyline inside the box."""
    out, cur = [], []
    for a, b in zip(line, line[1:]):
        seg = clip_segment(a, b, *box)
        if seg is None:
            if len(cur) > 1: out.append(cur)
            cur = []
            continue
        p, q = seg
        if cur and cur[-1] == p:
            cur.append(q)
        else:
            if len(cur) > 1: out.append(cur)
            cur = [p, q]
        if q != b:                      # left the box: the piece ends here
            out.append(cur); cur = []
    if len(cur) > 1: out.append(cur)
    return out


def main():
    index = {}
    for name in LAYERS:
        source = "coast" if name == "coastlow" else name
        feature = json.loads((GEO / f"{source}.json").read_text())
        lines = feature["geometry"]["coordinates"]
        if name == "coastlow":
            lines = thin_coast(lines)
        cells = {}
        for line in lines:
            xs = [p[0] for p in line]; ys = [p[1] for p in line]
            for cx in range(max(0, int((min(xs) + 180) // CELL)), min(11, int((max(xs) + 180) // CELL)) + 1):
                for cy in range(max(0, int((min(ys) + 90) // CELL)), min(5, int((max(ys) + 90) // CELL)) + 1):
                    box = (cx * CELL - 180, cy * CELL - 90, (cx + 1) * CELL - 180, (cy + 1) * CELL - 90)
                    pieces = clip_line(line, box)
                    if pieces:
                        cells.setdefault((cx, cy), []).extend(
                            [[round(x, 3), round(y, 3)] for x, y in piece] for piece in pieces)
        out = GEO / "tiles" / name
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("*.json"):
            old.unlink()
        total = 0
        for (cx, cy), parts in sorted(cells.items()):
            body = json.dumps({"type": "Feature", "properties": {},
                               "geometry": {"type": "MultiLineString", "coordinates": parts}},
                              separators=(",", ":"))
            (out / f"{cx}-{cy}.json").write_text(body)
            total += len(body)
        index[name] = [f"{cx}-{cy}" for cx, cy in sorted(cells)]
        print(f"{name}: {len(lines)} lines -> {len(cells)} cells, {total/1e6:.2f} MB "
              f"(original {(GEO / f'{source}.json').stat().st_size/1e6:.2f} MB)")
    (GEO / "tiles" / "index.json").write_text(json.dumps({"cell": CELL, "layers": index}, separators=(",", ":")))


if __name__ == "__main__":
    main()
