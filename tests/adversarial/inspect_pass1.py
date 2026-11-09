"""Inspect Pass 1 loop execution on 8x8 grid."""

import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_DIR))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if os.path.join(_ROOT, "core") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "core"))

from editmesh import EditMesh
from tests.mesh_factory import create_quad_grid
import dissolve
import numpy as np

v, f = create_quad_grid(nx=8, ny=8, dx=1.0, dy=1.0)
mesh = EditMesh.from_arrays(v, f)
cost_map = {e: 0.0 for e in mesh.edges}
protected_set = set(mesh.boundary_edges())

# Pass 0: Dissolve horizontal loops
# Collect all horizontal loops
all_h_loops = []
for e in mesh.edges:
    if e in protected_set:
        continue
    fl = dissolve.trace_full_transverse_loop(mesh, e, cost_map, protected_set)
    if fl:
        # Check direction
        c0 = mesh.vert_co(mesh.edge_verts(fl[0])[0])
        c1 = mesh.vert_co(mesh.edge_verts(fl[-1])[1])
        if abs(c0[1] - c1[1]) < 1e-4:  # horizontal line
            all_h_loops.append(fl)

# Greedy face-disjoint
used = set()
acc = []
for l in all_h_loops:
    fcs = set()
    for e in l:
        fcs.update(mesh.link_faces(e))
    if fcs & used:
        continue
    used |= fcs
    acc.append(l)

print(f"Pass 0 accepted {len(acc)} horizontal loops")
for l in acc:
    lverts = set()
    for e in l:
        v0, v1 = mesh.edge_verts(e)
        lverts.add(v0); lverts.add(v1)
        lf = mesh.link_faces(e)
        if len(lf) == 2:
            mesh.merge_faces([lf[0], lf[1]], dissolve_verts=False)
    mesh.dissolve_collinear_verts([v for v in lverts if v in mesh._vert_co], angle_tol_deg=10.0)

print(f"Post Pass 0: {len(mesh.faces)} faces, {len(mesh.edges)} edges, {len(mesh.verts)} verts")

# Now check Pass 1: Vertical loops!
cost_map1 = {e: 0.0 for e in mesh.edges}
protected_set1 = set(mesh.boundary_edges())
all_v_loops = []
for e in mesh.edges:
    if e in protected_set1:
        continue
    fl = dissolve.trace_full_transverse_loop(mesh, e, cost_map1, protected_set1)
    if fl:
        c0 = mesh.vert_co(mesh.edge_verts(fl[0])[0])
        c1 = mesh.vert_co(mesh.edge_verts(fl[-1])[1])
        all_v_loops.append((fl, c0, c1))

v_loops = [fl for fl, c0, c1 in all_v_loops if abs(c0[0] - c1[0]) < 1e-4]
h_loops = [fl for fl, c0, c1 in all_v_loops if abs(c0[1] - c1[1]) < 1e-4]
print(f"Pass 1: found {len(all_v_loops)} candidate loops: {len(h_loops)} horizontal, {len(v_loops)} vertical")
for fl in v_loops[:5]:
    print(f"  V-Loop len={len(fl)}, edges={fl}")
