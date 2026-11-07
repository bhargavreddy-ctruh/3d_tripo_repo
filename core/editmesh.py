"""A minimal mutable polygon mesh (vertices/edges/faces with adjacency),
replacing bmesh as the shared structure threaded through dissolve.py /
darts.py / coplanar_merge.py / caps.py / fix_winding.py / protect.py.

Unlike `trimesh.Trimesh` (triangle-only, array-backed), this preserves
arbitrary-arity faces (quads, n-gons) through in-place mutation, which the
stages above require (they build and merge quads/n-gons, not just
triangles).

IDs are plain incrementing integers, never reused within one EditMesh's
lifetime (no bmesh-style "-1 until renumbered" state to worry about).
`remove_face`/`remove_vert` free the underlying storage but never recycle
the id.
"""

import math

import numpy as np


class EditMesh:
    def __init__(self):
        self._vert_co = {}       # vid -> np.ndarray(3)
        self._vert_edges = {}    # vid -> set[eid]
        self._edge_verts = {}    # eid -> (v0, v1)
        self._edge_faces = {}    # eid -> list[fid]  (append order, like bmesh.link_faces)
        self._edge_key_to_id = {}  # frozenset({v0,v1}) -> eid
        self._face_verts = {}    # fid -> tuple[vid, ...]  (ordered loop)
        self._face_normal = {}   # fid -> np.ndarray(3) or None (lazy)
        self._next_vid = 0
        self._next_eid = 0
        self._next_fid = 0

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def add_vert(self, co):
        vid = self._next_vid
        self._next_vid += 1
        self._vert_co[vid] = np.asarray(co, dtype=float)
        self._vert_edges[vid] = set()
        return vid

    def _get_or_create_edge(self, v0, v1):
        key = frozenset((v0, v1))
        eid = self._edge_key_to_id.get(key)
        if eid is None:
            eid = self._next_eid
            self._next_eid += 1
            self._edge_key_to_id[key] = eid
            self._edge_verts[eid] = (v0, v1)
            self._edge_faces[eid] = []
            self._vert_edges[v0].add(eid)
            self._vert_edges[v1].add(eid)
        return eid

    def add_face(self, vert_ids):
        """vert_ids: ordered loop of >=3 vertex ids. Returns the new face id."""
        vert_ids = tuple(vert_ids)
        if len(vert_ids) < 3:
            raise ValueError(f"face needs >=3 verts, got {len(vert_ids)}")
        fid = self._next_fid
        self._next_fid += 1
        self._face_verts[fid] = vert_ids
        self._face_normal[fid] = None
        n = len(vert_ids)
        for i in range(n):
            v0, v1 = vert_ids[i], vert_ids[(i + 1) % n]
            eid = self._get_or_create_edge(v0, v1)
            self._edge_faces[eid].append(fid)
        return fid

    @classmethod
    def from_arrays(cls, vertices, faces):
        """vertices: (N,3) array-like. faces: list of vertex-index tuples
        (ragged, arbitrary arity, 0-based)."""
        mesh = cls()
        vid_of = [mesh.add_vert(co) for co in vertices]
        for f in faces:
            mesh.add_face([vid_of[i] for i in f])
        return mesh

    # ------------------------------------------------------------------
    # Removal
    # ------------------------------------------------------------------

    def remove_face(self, fid):
        vert_ids = self._face_verts.pop(fid)
        self._face_normal.pop(fid, None)
        n = len(vert_ids)
        for i in range(n):
            v0, v1 = vert_ids[i], vert_ids[(i + 1) % n]
            key = frozenset((v0, v1))
            eid = self._edge_key_to_id.get(key)
            if eid is None:
                continue
            lf = self._edge_faces.get(eid)
            if lf is not None:
                while fid in lf:
                    lf.remove(fid)
            if not lf:
                # Orphaned edge (no face references it any more) — drop it.
                del self._edge_faces[eid]
                del self._edge_verts[eid]
                del self._edge_key_to_id[key]
                self._vert_edges[v0].discard(eid)
                self._vert_edges[v1].discard(eid)

    def reverse_face(self, fid):
        """Flip a face's winding (reverses its vertex loop order). Edge
        bookkeeping is order-independent (keyed by frozenset), so this
        never touches edges — only the face's own vertex tuple and its
        cached normal."""
        self._face_verts[fid] = tuple(reversed(self._face_verts[fid]))
        self._face_normal[fid] = None

    def remove_vert(self, vid):
        """Only valid for an isolated (valence-0) vertex."""
        if self._vert_edges.get(vid):
            raise ValueError(f"vert {vid} still has {len(self._vert_edges[vid])} edges")
        self._vert_co.pop(vid, None)
        self._vert_edges.pop(vid, None)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def verts(self):
        return self._vert_co.keys()

    @property
    def edges(self):
        return self._edge_verts.keys()

    @property
    def faces(self):
        return self._face_verts.keys()

    def vert_co(self, vid):
        return self._vert_co[vid]

    def face_verts(self, fid):
        return self._face_verts[fid]

    def face_edges(self, fid):
        verts = self._face_verts[fid]
        n = len(verts)
        return [self._edge_key_to_id[frozenset((verts[i], verts[(i + 1) % n]))] for i in range(n)]

    def edge_verts(self, eid):
        return self._edge_verts[eid]

    def other_vert(self, eid, vid):
        v0, v1 = self._edge_verts[eid]
        return v1 if v0 == vid else v0

    def link_faces(self, eid):
        return self._edge_faces[eid]

    def link_edges(self, vid):
        return self._vert_edges[vid]

    def is_boundary(self, eid):
        return len(self._edge_faces[eid]) == 1

    def is_manifold(self, eid):
        return len(self._edge_faces[eid]) == 2

    def valence(self, vid):
        return len(self._vert_edges[vid])

    def face_normal(self, fid):
        n = self._face_normal.get(fid)
        if n is None:
            n = self._compute_normal(fid)
            self._face_normal[fid] = n
        return n

    def _compute_normal(self, fid):
        """Newell's method — matches Blender's face.normal for planar and
        non-planar n-gons alike."""
        verts = [self._vert_co[v] for v in self._face_verts[fid]]
        n = np.zeros(3)
        m = len(verts)
        for i in range(m):
            a, b = verts[i], verts[(i + 1) % m]
            n[0] += (a[1] - b[1]) * (a[2] + b[2])
            n[1] += (a[2] - b[2]) * (a[0] + b[0])
            n[2] += (a[0] - b[0]) * (a[1] + b[1])
        length = np.linalg.norm(n)
        if length < 1e-12:
            return n
        return n / length

    def recalc_face_normals(self):
        """Recompute every face's own Newell normal. Pure per-face math —
        O(F) with no traversal — safe to call every pass of a dissolve-style
        loop.

        NOTE: this does NOT fix winding consistency (unlike
        `bmesh.ops.recalc_face_normals`, which does both). Two adjacent
        faces with opposite winding have Newell normals pointing in
        near-opposite directions even where the surface is locally flat,
        which makes every normal-angle-based test downstream (protect.py's
        crease/dome-saddle rules, coplanar_merge.py's flood fill) see false
        huge deviations on an otherwise flat region — confirmed directly:
        on inconsistently-wound input, skipping a winding fix made
        protect.py hard-protect ~98% of a real decimated component's edges
        instead of the correct ~73%. Call `fix_winding_consistency()`
        explicitly first (once, not per pass) whenever the mesh's winding
        isn't already known-consistent — e.g. once at the start of each
        finalize stage, since remesh output isn't guaranteed consistent and
        `merge_faces` only guarantees a NEW face matches whichever neighbor
        it checks, not global consistency on pre-existing inconsistent
        input."""
        for fid in list(self._face_verts):
            self._face_normal[fid] = self._compute_normal(fid)

    def fix_winding_consistency(self):
        """Flood-fill face winding consistency via edge-direction
        comparison (the same algorithm `trimesh.repair.fix_winding` uses,
        adapted to arbitrary-arity faces). Returns the number of faces
        flipped. Skips non-manifold edges (<2 or >2 link faces) as
        traversal edges — a genuine non-manifold junction has no single
        well-defined consistent choice, but still comparing against each
        unvisited linked face keeps the traversal graph connected far
        better than skipping those edges outright.
        """
        vert_index_cache = {}

        def vert_map(face):
            m = vert_index_cache.get(face)
            if m is None:
                verts = list(self._face_verts[face])
                m = ({v: i for i, v in enumerate(verts)}, verts)
                vert_index_cache[face] = m
            return m

        def raw_forward(face, a, b):
            idx, verts = vert_map(face)
            n = len(verts)
            return verts[(idx[a] + 1) % n] == b

        flip_decision = {}
        visited = set()

        for seed in self._face_verts:
            if seed in visited:
                continue
            visited.add(seed)
            flip_decision[seed] = False
            stack = [seed]
            while stack:
                f = stack.pop()
                for e in self.face_edges(f):
                    if len(self._edge_faces[e]) < 2:
                        continue
                    a, b = self._edge_verts[e]
                    f_eff = raw_forward(f, a, b) != flip_decision[f]
                    for other in self._edge_faces[e]:
                        if other == f or other in visited:
                            continue
                        visited.add(other)
                        other_raw = raw_forward(other, a, b)
                        flip_decision[other] = (other_raw == f_eff)
                        stack.append(other)

        faces_to_flip = [f for f, flip in flip_decision.items() if flip]
        for f in faces_to_flip:
            self.reverse_face(f)
        return len(faces_to_flip)

    def calc_area(self, fid):
        """3D polygon area using Newell's method (Stokes' theorem contour
        integration) — robust to polygon shape and orientation, eliminating
        fan-triangulation drift artifacts on flat non-convex boundaries."""
        verts = [self._vert_co[v] for v in self._face_verts[fid]]
        if len(verts) < 3:
            return 0.0
        coords = np.array(verts)
        newell = np.zeros(3)
        n = len(coords)
        for i in range(n):
            c1, c2 = coords[i], coords[(i + 1) % n]
            newell[0] += (c1[1] - c2[1]) * (c1[2] + c2[2])
            newell[1] += (c1[2] - c2[2]) * (c1[0] + c2[0])
            newell[2] += (c1[0] - c2[0]) * (c1[1] + c2[1])
        return 0.5 * float(np.linalg.norm(newell))

    def total_area(self):
        return sum(self.calc_area(f) for f in self._face_verts)

    def boundary_edges(self):
        return [e for e in self._edge_verts if self.is_boundary(e)]

    def non_manifold_edges(self):
        return [e for e in self._edge_verts if len(self._edge_faces[e]) > 2]

    def count_islands(self):
        """Connected components over the vertex/edge graph, counting only
        vertices actually used by at least one face.

        REAL BUG, found 2026-11-04: counting every vertex in `_vert_co`
        (including ones no face references) treats each stray/unreferenced
        vertex as its OWN extra island. Confirmed directly: a real Instant
        Meshes OBJ output had 124 such leftover vertices (not referenced by
        any face in the final output, but still written to the file) on an
        otherwise perfectly single-island mesh, inflating the reported
        island count from 1 to 125. An unreferenced vertex isn't a piece of
        geometry at all, so it shouldn't count as one.
        """
        used_verts = set()
        for f in self._face_verts:
            used_verts.update(self._face_verts[f])

        visited = set()
        islands = 0
        for seed in used_verts:
            if seed in visited:
                continue
            islands += 1
            stack = [seed]
            visited.add(seed)
            while stack:
                v = stack.pop()
                for e in self._vert_edges[v]:
                    other = self.other_vert(e, v)
                    if other not in visited:
                        visited.add(other)
                        stack.append(other)
        return islands

    def bounding_box_diagonal(self):
        if not self._vert_co:
            return 1.0
        coords = np.array(list(self._vert_co.values()))
        diag = float(np.linalg.norm(coords.max(axis=0) - coords.min(axis=0)))
        return diag if diag > 0 else 1.0

    def to_arrays(self):
        """Returns (vertices (N,3) array, faces list[tuple[int,...]],
        vid_to_index dict) with compact 0-based indices — for interop with
        trimesh/igl calls elsewhere in the pipeline."""
        vids = sorted(self._vert_co.keys())
        vid_to_index = {v: i for i, v in enumerate(vids)}
        vertices = np.array([self._vert_co[v] for v in vids]) if vids else np.zeros((0, 3))
        faces = [tuple(vid_to_index[v] for v in self._face_verts[f]) for f in self._face_verts]
        return vertices, faces, vid_to_index

    # ------------------------------------------------------------------
    # Boundary-walk / disk-topology / face-cluster merge — the one shared
    # primitive behind dissolve.py's dissolve_edges-equivalent,
    # coplanar_merge.py's dissolve_faces-equivalent, and darts.py's
    # join_triangles-equivalent: "replace a connected face cluster with one
    # n-gon bounded by its outer walk."
    # ------------------------------------------------------------------

    def _walk_boundary_loop(self, boundary_edges):
        """boundary_edges: iterable of edge ids forming the outer boundary
        of some face cluster. Returns an ordered vertex loop if they form
        exactly ONE simple cycle, else None (mirrors
        coplanar_merge.py's `_is_disk_topology`, but also returns the
        ordering needed to build the replacement face)."""
        boundary_edges = list(boundary_edges)
        if not boundary_edges:
            return None
        adjacency = {}
        for e in boundary_edges:
            v0, v1 = self._edge_verts[e]
            adjacency.setdefault(v0, []).append(e)
            adjacency.setdefault(v1, []).append(e)

        start_e = boundary_edges[0]
        v0, v1 = self._edge_verts[start_e]
        loop_verts = [v0]
        visited_edges = {start_e}
        cur_v = v1
        steps = 0
        while cur_v != v0:
            loop_verts.append(cur_v)
            candidates = [e for e in adjacency.get(cur_v, []) if e not in visited_edges]
            if not candidates:
                return None  # dead end — not a closed loop
            nxt = candidates[0]
            visited_edges.add(nxt)
            cur_v = self.other_vert(nxt, cur_v)
            steps += 1
            if steps > len(boundary_edges) + 1:
                return None  # degenerate walk, bail out safely

        if len(visited_edges) != len(boundary_edges):
            return None  # more than one boundary loop — not disk topology
        return loop_verts

    def _orient_loop_like_neighbor(self, loop, boundary_edges, face_set):
        """Pick the traversal direction (loop, or reversed(loop)) that keeps
        the new face's winding consistent with whichever neighboring
        (non-cluster) face already borders this cluster — i.e. on a
        manifold edge shared between the new face and an outside face, the
        two faces must traverse that edge in OPPOSITE directions.

        Without this, a merge's winding is arbitrary (whatever direction
        `_walk_boundary_loop` happened to start in), so every single merge
        risks leaving the mesh winding-inconsistent — which is exactly what
        made `recalc_face_normals()` need a full mesh-wide winding-fix BFS
        on every call. Orienting correctly here means winding only needs
        fixing once per stage (on genuinely inconsistent input), not once
        per merge.
        """
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            eid = self._edge_key_to_id.get(frozenset((a, b)))
            if eid is None:
                continue
            outside_faces = [f for f in self._edge_faces[eid] if f not in face_set]
            if not outside_faces:
                continue
            outside = outside_faces[0]
            verts = self._face_verts[outside]
            m = len(verts)
            idx = verts.index(a)
            outside_forward = verts[(idx + 1) % m] == b  # outside face visits a->b
            # A consistent mesh traverses a shared edge in opposite directions
            # from its two faces — our loop currently visits a->b (since
            # loop[i]=a, loop[i+1]=b), so if the outside face ALSO visits
            # a->b, we must reverse.
            if outside_forward:
                return list(reversed(loop))
            return loop
        return loop  # no outside neighbor on this cluster's boundary — orientation is free

    def merge_faces(self, face_ids, dissolve_verts=False, collinear_angle_tol_deg=1.0,
                     max_area_drift_frac=0.1):
        """Replace the given connected face cluster with ONE new face
        bounded by its outer walk (the shared primitive behind
        dissolve_edges/dissolve_faces/join_triangles). Returns the new face
        id, or None if the cluster isn't a single simple-boundary disk, or
        if accepting the merge would distort the surface too much
        (nothing is mutated in either case).

        dissolve_verts=True additionally removes now-redundant collinear
        vertices from the new face's own boundary loop afterward (the
        `use_verts=True` behavior dissolve.py relies on); dissolve_verts=False
        never touches a vertex, so a vertex shared with a face outside the
        cluster (a T-junction) is always left intact (the `use_verts=False`
        safety coplanar_merge.py relies on).

        max_area_drift_frac: reject (roll back) a merge whose new face's
        own fan-triangulated area differs from the summed original faces'
        area by more than this fraction. Found necessary directly: on a
        strongly curved surface, a long transverse-loop merge can produce a
        valid (non-self-intersecting) but strongly non-convex/non-planar
        n-gon — topologically fine, but `calc_area`'s fan-triangulation
        from one arbitrary vertex (and every other tool's, including a
        viewer's own flat-triangulation of the same n-gon for display)
        becomes unreliable on a shape like that, visibly: confirmed one
        real asset where a single pass's merges inflated total triangulated
        area by 21% and rendered as a field of sawtooth spikes, while
        Blender's bmesh produced a near-zero-drift, visually clean result
        on the SAME input mesh — bmesh's dissolve_edges evidently does not
        accept a merge this distorting either. Rejecting here (leaving the
        smaller original faces in place, to be reconsidered next pass) is
        the direct fix.
        """
        face_set = set(face_ids)
        if len(face_set) < 2:
            return None
        boundary_edges = []
        seen = set()
        for fid in face_set:
            for eid in self.face_edges(fid):
                if eid in seen:
                    continue
                seen.add(eid)
                internal = sum(1 for lf in self._edge_faces[eid] if lf in face_set)
                if internal < 2:
                    boundary_edges.append(eid)

        loop = self._walk_boundary_loop(boundary_edges)
        if loop is None:
            return None
        loop = self._orient_loop_like_neighbor(loop, boundary_edges, face_set)

        area_before = sum(self.calc_area(fid) for fid in face_set)

        # Any vertex strictly interior to the cluster (e.g. the apex of a
        # fan of faces all meeting at one point, with every one of its
        # edges internal to the cluster) will end up with zero edges once
        # the cluster's faces are removed below — it's not on the new
        # face's boundary loop, so nothing will ever reference it again.
        # Garbage-collect it now rather than leaving a phantom valence-0
        # vertex behind (bmesh's dissolve_faces/dissolve_edges do this
        # implicitly; count_islands() would otherwise count each such
        # leftover vertex as its own bogus extra island).
        loop_set = set(loop)
        interior_candidates = {v for fid in face_set for v in self._face_verts[fid]} - loop_set

        saved_faces = [self._face_verts[fid] for fid in face_set]
        for fid in face_set:
            self.remove_face(fid)
        new_fid = self.add_face(loop)

        area_after = self.calc_area(new_fid)
        if area_before > 1e-12:
            drift = abs(area_after - area_before) / area_before
            if drift > max_area_drift_frac:
                # Roll back: remove the merged face, restore the originals.
                self.remove_face(new_fid)
                for verts in saved_faces:
                    self.add_face(verts)
                return None

        for v in interior_candidates:
            if not self._vert_edges.get(v):
                self.remove_vert(v)

        if dissolve_verts:
            self.dissolve_collinear_verts(loop, angle_tol_deg=collinear_angle_tol_deg)

        return new_fid

    def dissolve_collinear_verts(self, candidate_vids, angle_tol_deg=1.0, max_passes=10):
        """Remove any given valence-2 vertex whose two remaining edges are
        nearly opposite in direction (i.e. it sits on the straight line
        between its two neighbors), splicing its two edges' faces into one
        shorter loop. Mirrors coplanar_merge.py's
        `dissolve_collinear_vertices`. Returns the number removed.

        Bounded multi-pass: removing one collinear vertex can leave a
        neighbor newly collinear (its edge to the removed vertex is
        replaced by a direct edge to the far neighbor) — re-scan the same
        candidate pool up to max_passes times to catch short chains, same
        as the original bmesh-based implementation."""
        candidates_pool = list(candidate_vids)
        removed = 0
        for _pass in range(max_passes):
            n_removed_this_pass = self._dissolve_collinear_pass(candidates_pool, angle_tol_deg)
            removed += n_removed_this_pass
            if n_removed_this_pass == 0:
                break
        return removed

    def _dissolve_collinear_pass(self, candidate_vids, angle_tol_deg):
        cos_thresh = -math.cos(math.radians(angle_tol_deg))
        removed = 0
        for v in list(candidate_vids):
            if v not in self._vert_edges:
                continue
            edges = list(self._vert_edges[v])
            if len(edges) != 2:
                continue
            e0, e1 = edges
            if self.is_boundary(e0) != self.is_boundary(e1):
                continue  # don't mix a true mesh boundary edge with an interior one
            other0 = self.other_vert(e0, v)
            other1 = self.other_vert(e1, v)
            dir0 = self._vert_co[other0] - self._vert_co[v]
            dir1 = self._vert_co[other1] - self._vert_co[v]
            n0, n1 = np.linalg.norm(dir0), np.linalg.norm(dir1)
            if n0 < 1e-9 or n1 < 1e-9:
                continue
            dir0, dir1 = dir0 / n0, dir1 / n1
            if float(np.dot(dir0, dir1)) >= cos_thresh:
                continue  # not collinear enough

            faces_touching = set(self._edge_faces[e0]) | set(self._edge_faces[e1])
            rebuilt = []
            ok = True
            for fid in faces_touching:
                verts = list(self._face_verts[fid])
                if v not in verts:
                    continue
                idx = verts.index(v)
                new_verts = tuple(verts[:idx] + verts[idx + 1:])
                if len(new_verts) < 3:
                    ok = False
                    break
                rebuilt.append(new_verts)
            if not ok:
                continue

            for fid in list(faces_touching):
                if v in self._face_verts.get(fid, ()):
                    self.remove_face(fid)
            for nv in rebuilt:
                self.add_face(nv)
            self.remove_vert(v)
            removed += 1
        return removed
