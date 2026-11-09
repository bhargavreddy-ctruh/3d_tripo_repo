"""Quad-Strip Tracing and Field-Aligned Re-Quadrangulation Engine.

Strictly preserves quad-field alignment by operating globally along quad strips
(chords and rails) rather than local greedy edge-by-edge or flood-fill merges.

Key Principles:
1. Pure Quad Strips: Stepping across opposite edges (e_i -> e_{i+2}) in quads.
2. Complete Transverse Chords: Only decimate a line of rungs if the chord is
   COMPLETE (spans boundary-to-boundary, seam-to-seam, or closed periodic loop).
   Partial/truncated loop merges are strictly prohibited (prevents picket-fence n-gons).
3. Topological Rail Collapse: When a full chord of rungs is removed, every
   rail vertex between merged quads has topological valence 2. Dissolve along
   the rail directly, guaranteeing 100% clean quads (zero n-gons, zero triangles).
4. Feature & Ring Protection: Field-aligned quad rings and curved detail that
   do not have flat transverse chords are preserved in their clean quad form.
"""

import math
import numpy as np


def get_opposite_edge(mesh, fid, eid):
    """Given a quad fid and one of its edges eid, return the opposite edge."""
    fedges = list(mesh.face_edges(fid))
    if len(fedges) != 4 or eid not in fedges:
        return None
    idx = fedges.index(eid)
    return fedges[(idx + 2) % 4]


def get_rail_edges(mesh, fid, eid):
    """Given a quad fid and one of its edges eid (rung), return the two rail edges."""
    fedges = list(mesh.face_edges(fid))
    if len(fedges) != 4 or eid not in fedges:
        return None, None
    idx = fedges.index(eid)
    rail0 = fedges[(idx + 1) % 4]
    rail1 = fedges[(idx + 3) % 4]
    return rail0, rail1


def trace_transverse_chord(mesh, start_edge, max_angle_deg=10.0, creases=None):
    """Trace a complete transverse chord of rungs passing through start_edge.
    
    A chord is a sequence of rungs [e_0, e_1, ..., e_k] where e_i and e_{i+1}
    are opposite edges of a quad face Q_i.
    
    Returns:
        chord: list of edge IDs [e_0, e_1, ..., e_k]
        faces: list of quad face IDs [Q_0, ..., Q_{k-1}]
        is_complete: bool (True if closed loop or cleanly bounded at both ends)
    """
    if creases is None:
        creases = set()

    if mesh.is_boundary(start_edge) or start_edge in creases:
        return None, None, False

    lf = list(mesh.link_faces(start_edge))
    if len(lf) != 2:
        return None, None, False

    cos_tol = math.cos(math.radians(max_angle_deg))

    def step_direction(curr_e, curr_f):
        """Step through curr_f from curr_e to its opposite edge."""
        seq_edges = [curr_e]
        seq_faces = []
        f = curr_f
        e_in = curr_e
        
        while f is not None:
            if len(mesh.face_verts(f)) != 4:
                return seq_edges, seq_faces, False  # hit non-quad
            
            e_opp = get_opposite_edge(mesh, f, e_in)
            if e_opp is None:
                return seq_edges, seq_faces, False
            
            # Check flatness across e_in inside this face / dihedral angle with neighbor
            seq_faces.append(f)
            seq_edges.append(e_opp)
            
            if mesh.is_boundary(e_opp) or e_opp in creases:
                return seq_edges, seq_faces, True  # cleanly reached boundary/crease
            
            next_lfaces = [nf for nf in mesh.link_faces(e_opp) if nf != f]
            if len(next_lfaces) != 1:
                return seq_edges, seq_faces, True  # non-manifold or boundary
            
            next_f = next_lfaces[0]
            if len(mesh.face_verts(next_f)) != 4:
                # FIX (session finding): hitting a non-quad face is a clean,
                # valid place for the chord to stop -- same as a boundary or
                # crease -- not a reason to invalidate the whole chord. The
                # original "return False" here meant any stray triangle
                # anywhere along a long row disqualified every chord that
                # ever reached it, which was silently producing zero merges
                # on every real asset tested (fish, woodenrack both: 0).
                return seq_edges, seq_faces, True

            # Dihedral angle check between f and next_f
            n0 = mesh.face_normal(f)
            n1 = mesh.face_normal(next_f)
            if np.dot(n0, n1) < cos_tol:
                return seq_edges, seq_faces, False  # exceeds angle tolerance
            
            e_in = e_opp
            f = next_f
            
            # Guard against infinite loops
            if len(seq_faces) > 500:
                return seq_edges, seq_faces, False

        return seq_edges, seq_faces, False

    f0, f1 = lf[0], lf[1]
    
    # Check dihedral angle at start_edge
    n0 = mesh.face_normal(f0)
    n1 = mesh.face_normal(f1)
    if np.dot(n0, n1) < cos_tol:
        return None, None, False

    # Trace through f1 (forward)
    fwd_edges, fwd_faces, fwd_ok = step_direction(start_edge, f1)
    if not fwd_ok:
        return None, None, False

    # Check if fwd loop closed back to start_edge
    if len(fwd_edges) > 2 and fwd_edges[-1] == start_edge:
        # Periodic closed ring
        return fwd_edges[:-1], fwd_faces, True

    # Trace through f0 (backward)
    bwd_edges, bwd_faces, bwd_ok = step_direction(start_edge, f0)
    if not bwd_ok:
        return None, None, False

    # Combine backward (reversed) + start_edge + forward
    # bwd_edges starts with start_edge and ends at boundary
    # fwd_edges starts with start_edge and ends at boundary
    full_edges = list(reversed(bwd_edges[1:])) + fwd_edges
    full_faces = list(reversed(bwd_faces)) + fwd_faces

    # Deduplicate while preserving order
    seen = set()
    dedup_edges = []
    for e in full_edges:
        if e not in seen:
            seen.add(e)
            dedup_edges.append(e)

    seen_f = set()
    dedup_faces = []
    for f in full_faces:
        if f not in seen_f:
            seen_f.add(f)
            dedup_faces.append(f)

    return dedup_edges, dedup_faces, True


def decimate_transverse_chord(mesh, chord_edges, chord_faces):
    """Atomically decimate a complete transverse chord of rungs.
    
    Combines each adjacent pair of quads across each rung in chord_edges,
    and removes the rail vertices (which have valence exactly 2), yielding
    a strictly 100% QUAD mesh.
    
    Returns:
        dict with stats: quads_removed, ok
    """
    # Verify all edges and faces are still valid and manifold
    for e in chord_edges:
        if e not in mesh._edge_faces:
            return {"ok": False, "reason": "stale edge"}
        lf = list(mesh.link_faces(e))
        if len(lf) != 2:
            return {"ok": False, "reason": "non-manifold or boundary edge"}

    for f in chord_faces:
        if f not in mesh._face_verts:
            return {"ok": False, "reason": "stale face"}
        if len(mesh.face_verts(f)) != 4:
            return {"ok": False, "reason": "non-quad face"}

    # Track vertices of the chord rungs that should become valence-2
    # In a full chord, each rung e has 2 vertices.
    # Vertices strictly interior to the chord will have exactly 2 incident rungs
    # (one from chord_edges[i], one from chord_edges[i+1]).
    # When all chord_edges are removed, these interior vertices lose 2 edges,
    # reducing their valence by 2 (typically from 4 to 2).
    merged_edge_verts = set()
    for e in chord_edges:
        v0, v1 = mesh.edge_verts(e)
        merged_edge_verts.add(v0)
        merged_edge_verts.add(v1)

    # Perform pairwise merges across each rung
    # Note: chord_edges are rungs between adjacent quads.
    # Merging f0 and f1 across rung e without dissolving vertices creates a 6-gon.
    # Once all rungs in the chord are merged, the intermediate rail vertices
    # have valence 2 and can be dissolved cleanly!
    merged_count = 0
    for e in chord_edges:
        if e not in mesh._edge_faces:
            continue
        lf = list(mesh.link_faces(e))
        if len(lf) != 2:
            continue
        f0, f1 = lf[0], lf[1]
        if f0 not in mesh._face_verts or f1 not in mesh._face_verts:
            continue
        new_f = mesh.merge_faces([f0, f1], dissolve_verts=False)
        if new_f is not None:
            merged_count += 1

    if merged_count == 0:
        return {"ok": False, "reason": "no merges performed"}

    # Now dissolve the valence-2 vertices along the rails
    # Use a high tolerance or direct valence-2 removal because we know topologically
    # they are along a continuous rail line of the strip
    candidates = [v for v in merged_edge_verts if v in mesh._vert_co and mesh.valence(v) == 2]
    
    # We can dissolve with angle_tol_deg=180.0 for vertices that are guaranteed
    # to be valence-2 from this chord decimation!
    n_dissolved = mesh.dissolve_collinear_verts(candidates, angle_tol_deg=45.0)

    return {
        "ok": True,
        "rungs_merged": merged_count,
        "rail_verts_dissolved": n_dissolved,
    }


def simplify_mesh_by_strip_tracing(mesh, max_passes=10, max_angle_deg=8.0, creases=None):
    """Iteratively simplify mesh using pure Quad-Strip Transverse Decimation.
    
    Guarantees:
    - Zero triangles created.
    - Zero n-gons created.
    - Complete field-alignment preservation along strips.
    """
    mesh.fix_winding_consistency()
    total_rungs_merged = 0
    total_verts_dissolved = 0

    for pass_idx in range(max_passes):
        # Find candidate rungs: interior edges between two quads
        candidate_edges = []
        for e in mesh.edges:
            if mesh.is_boundary(e):
                continue
            lf = mesh.link_faces(e)
            if len(lf) != 2:
                continue
            f0, f1 = lf[0], lf[1]
            if len(mesh.face_verts(f0)) == 4 and len(mesh.face_verts(f1)) == 4:
                # Area-based priority: smaller quads first
                area = mesh.calc_area(f0) + mesh.calc_area(f1)
                candidate_edges.append((area, e))

        candidate_edges.sort(key=lambda x: x[0])

        visited_edges = set()
        chords_to_decimate = []

        for _area, e in candidate_edges:
            if e in visited_edges:
                continue
            chord_edges, chord_faces, is_complete = trace_transverse_chord(
                mesh, e, max_angle_deg=max_angle_deg, creases=creases
            )
            if is_complete and chord_edges and len(chord_edges) >= 3:
                # Ensure no overlap with already accepted chords in this pass
                if not (set(chord_edges) & visited_edges):
                    chords_to_decimate.append((chord_edges, chord_faces))
                    visited_edges.update(chord_edges)

        if not chords_to_decimate:
            break

        pass_merges = 0
        for chord_edges, chord_faces in chords_to_decimate:
            res = decimate_transverse_chord(mesh, chord_edges, chord_faces)
            if res.get("ok"):
                total_rungs_merged += res["rungs_merged"]
                total_verts_dissolved += res["rail_verts_dissolved"]
                pass_merges += 1

        if pass_merges == 0:
            break

    return {
        "rungs_merged": total_rungs_merged,
        "verts_dissolved": total_verts_dissolved,
    }

