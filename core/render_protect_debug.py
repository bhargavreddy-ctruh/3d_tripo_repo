"""Render a protected-edge-colored wireframe from protect.py's dump, for
the required eye-check (don't trust aggregate stats alone)."""
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Line3DCollection
import numpy as np


def render(dump_json, out_png):
    with open(dump_json) as fh:
        data = json.load(fh)
    edges = data["edges"]

    protected_segs = [[e["p0"], e["p1"]] for e in edges if e["protected"]]
    free_segs = [[e["p0"], e["p1"]] for e in edges if not e["protected"]]
    free_costs = np.array([e["cost"] for e in edges if not e["protected"]])

    fig = plt.figure(figsize=(9, 9))
    ax = fig.add_subplot(111, projection="3d")

    if free_segs:
        lo, hi = np.percentile(free_costs, [2, 98]) if len(free_costs) > 1 else (0, 1)
        hi = max(hi, lo + 1e-9)
        norm = np.clip((free_costs - lo) / (hi - lo), 0, 1)
        cmap = plt.get_cmap("viridis")
        colors = cmap(norm)
        lc = Line3DCollection(free_segs, colors=colors, linewidths=0.8)
        ax.add_collection3d(lc)

    if protected_segs:
        lc2 = Line3DCollection(protected_segs, colors=[(1, 0, 0, 1)], linewidths=1.6)
        ax.add_collection3d(lc2)

    all_pts = np.array([e["p0"] for e in edges] + [e["p1"] for e in edges])
    mins, maxs = all_pts.min(axis=0), all_pts.max(axis=0)
    center = (mins + maxs) / 2
    span = (maxs - mins).max() / 2 * 1.1
    ax.set_xlim(center[0] - span, center[0] + span)
    ax.set_ylim(center[1] - span, center[1] + span)
    ax.set_zlim(center[2] - span, center[2] + span)
    ax.set_box_aspect([1, 1, 1])
    ax.set_axis_off()
    ax.set_title(f"Red = hard-protected ({len(protected_segs)}/{len(edges)}), "
                 f"viridis = finite cost (dark=cheap to dissolve)")

    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Rendered {out_png}")


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2])
