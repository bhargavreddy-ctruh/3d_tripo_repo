"""Procedural mesh generation fixtures for 4-tier E2E testing suite.

Generates precise geometric topologies:
- Regular quad grids and planar panels
- Watertight closed solids (cubes, cylinders, spheres)
- Planar panels with circular/rectangular internal holes
- High-valence starbursts and fan-triangulated annular polygons
- Needle triangles, slivers, and 1D barcode slats
- Degenerate topologies (collinear vertices, cracks, non-manifold edges)
"""

import math
import numpy as np


def create_quad_grid(nx=4, ny=4, dx=1.0, dy=1.0, z=0.0):
    """Generate a regular (nx x ny) quad grid on the XY plane.
    Returns (vertices: np.ndarray, faces: list[tuple[int,...]]).
    """
    verts = []
    for j in range(ny + 1):
        for i in range(nx + 1):
            verts.append([i * dx, j * dy, z])

    faces = []
    for j in range(ny):
        for i in range(nx):
            v0 = j * (nx + 1) + i
            v1 = v0 + 1
            v2 = (j + 1) * (nx + 1) + i + 1
            v3 = (j + 1) * (nx + 1) + i
            faces.append((v0, v1, v2, v3))

    return np.array(verts, dtype=float), faces


def create_quad_box(w=1.0, h=1.0, d=1.0, sub_x=2, sub_y=2, sub_z=2):
    """Generate a watertight closed cube composed of 100% quads.
    Subdivided into regular grids on all 6 faces.
    """
    verts = []
    faces = []
    v_offset = 0

    def add_face_grid(origin, u_axis, v_axis, nu, nv, du, dv):
        nonlocal v_offset
        for j in range(nv + 1):
            for i in range(nu + 1):
                pt = origin + i * du * u_axis + j * dv * v_axis
                verts.append(pt.tolist())

        for j in range(nv):
            for i in range(nu):
                v0 = v_offset + j * (nu + 1) + i
                v1 = v_offset + j * (nu + 1) + i + 1
                v2 = v_offset + (j + 1) * (nu + 1) + i + 1
                v3 = v_offset + (j + 1) * (nu + 1) + i
                faces.append((v0, v1, v2, v3))
        v_offset += (nu + 1) * (nv + 1)

    # 6 faces of the box
    ux = np.array([1.0, 0.0, 0.0])
    uy = np.array([0.0, 1.0, 0.0])
    uz = np.array([0.0, 0.0, 1.0])

    # Bottom (Z=0)
    add_face_grid(np.array([0.0, 0.0, 0.0]), ux, uy, sub_x, sub_y, w / sub_x, h / sub_y)
    # Top (Z=d)
    add_face_grid(np.array([0.0, h, d]), ux, -uy, sub_x, sub_y, w / sub_x, h / sub_y)
    # Front (Y=0)
    add_face_grid(np.array([0.0, 0.0, d]), ux, -uz, sub_x, sub_z, w / sub_x, d / sub_z)
    # Back (Y=h)
    add_face_grid(np.array([w, h, d]), -ux, -uz, sub_x, sub_z, w / sub_x, d / sub_z)
    # Left (X=0)
    add_face_grid(np.array([0.0, h, d]), -uy, -uz, sub_y, sub_z, h / sub_y, d / sub_z)
    # Right (X=w)
    add_face_grid(np.array([w, 0.0, d]), uy, -uz, sub_y, sub_z, h / sub_y, d / sub_z)

    # Weld coincident vertices at box edges to make watertight
    verts_arr = np.array(verts, dtype=float)
    unique_verts, inverse_indices = _weld_vertices(verts_arr, tol=1e-5)
    welded_faces = [tuple(inverse_indices[vi] for vi in f) for f in faces]

    return unique_verts, welded_faces


def create_quad_cylinder(radius=1.0, height=2.0, n_theta=16, n_z=4, closed=True):
    """Generate a quad-dominant cylinder surface.
    Body is 100% quads. If closed=True, caps are closed with quads/tris.
    """
    verts = []
    # Generate side vertices
    for j in range(n_z + 1):
        z = (j / n_z) * height
        for i in range(n_theta):
            theta = (2.0 * math.pi * i) / n_theta
            x = radius * math.cos(theta)
            y = radius * math.sin(theta)
            verts.append([x, y, z])

    faces = []
    for j in range(n_z):
        for i in range(n_theta):
            i_next = (i + 1) % n_theta
            v0 = j * n_theta + i
            v1 = j * n_theta + i_next
            v2 = (j + 1) * n_theta + i_next
            v3 = (j + 1) * n_theta + i
            faces.append((v0, v1, v2, v3))

    if closed:
        # Bottom cap center
        bot_center_idx = len(verts)
        verts.append([0.0, 0.0, 0.0])
        # Top cap center
        top_center_idx = len(verts)
        verts.append([0.0, 0.0, height])

        # Bottom cap tris
        for i in range(n_theta):
            i_next = (i + 1) % n_theta
            faces.append((bot_center_idx, i_next, i))

        # Top cap tris
        top_offset = n_z * n_theta
        for i in range(n_theta):
            i_next = (i + 1) % n_theta
            faces.append((top_center_idx, top_offset + i, top_offset + i_next))

    return np.array(verts, dtype=float), faces


def create_quad_sphere(radius=1.0, n_lat=8, n_lon=16):
    """Generate a quad-dominant UV sphere (caps are tris, interior all quads)."""
    verts = []
    # North pole
    verts.append([0.0, 0.0, radius])
    north_pole = 0

    for i in range(1, n_lat):
        phi = math.pi * i / n_lat
        z = radius * math.cos(phi)
        r_xy = radius * math.sin(phi)
        for j in range(n_lon):
            theta = 2.0 * math.pi * j / n_lon
            x = r_xy * math.cos(theta)
            y = r_xy * math.sin(theta)
            verts.append([x, y, z])

    # South pole
    south_pole = len(verts)
    verts.append([0.0, 0.0, -radius])

    faces = []
    # North pole tris
    for j in range(n_lon):
        j_next = (j + 1) % n_lon
        faces.append((north_pole, 1 + j, 1 + j_next))

    # Body quads
    for i in range(n_lat - 2):
        row0 = 1 + i * n_lon
        row1 = 1 + (i + 1) * n_lon
        for j in range(n_lon):
            j_next = (j + 1) % n_lon
            faces.append((row0 + j, row1 + j, row1 + j_next, row0 + j_next))

    # South pole tris
    last_row = 1 + (n_lat - 2) * n_lon
    for j in range(n_lon):
        j_next = (j + 1) % n_lon
        faces.append((south_pole, last_row + j_next, last_row + j))

    return np.array(verts, dtype=float), faces


def create_planar_collar_panel(size=4.0, hole_radius=0.6, collar_radius=1.2, n_pts=8):
    """Create a planar panel with an internal circular hole protected by a clean quad collar.
    Topology: quad collar around hole, quad grid bridging to outer boundary.
    Strictly 100% quads with isotropic aspect ratios < 2.0.
    """
    verts = []
    # Inner hole circle (r = hole_radius)
    inner_indices = []
    for i in range(n_pts):
        angle = 2.0 * math.pi * i / n_pts
        verts.append([hole_radius * math.cos(angle), hole_radius * math.sin(angle), 0.0])
        inner_indices.append(i)

    # Collar outer circle (r = collar_radius)
    collar_indices = []
    for i in range(n_pts):
        angle = 2.0 * math.pi * i / n_pts
        verts.append([collar_radius * math.cos(angle), collar_radius * math.sin(angle), 0.0])
        collar_indices.append(n_pts + i)

    # Outer square boundary (8 perimeter vertices matching n_pts=8)
    half = size / 2.0
    square_corners = [
        [half, 0.0, 0.0],
        [half, half, 0.0],
        [0.0, half, 0.0],
        [-half, half, 0.0],
        [-half, 0.0, 0.0],
        [-half, -half, 0.0],
        [0.0, -half, 0.0],
        [half, -half, 0.0],
    ]
    outer_indices = []
    for pt in square_corners:
        verts.append(pt)
        outer_indices.append(len(verts) - 1)

    faces = []
    # 1. Collar ring of quads
    for i in range(n_pts):
        i_next = (i + 1) % n_pts
        faces.append((inner_indices[i], inner_indices[i_next], collar_indices[i_next], collar_indices[i]))

    # 2. Outer bridge ring of quads
    for i in range(n_pts):
        i_next = (i + 1) % n_pts
        faces.append((collar_indices[i], collar_indices[i_next], outer_indices[i_next], outer_indices[i]))

    return np.array(verts, dtype=float), faces


def create_annular_ngon_mesh(size=4.0, hole_radius=0.6, n_inner=16):
    """Create a defective mesh matching the failure described in the RCA:
    A giant annular N-gon enclosing an internal hole, without collar partition.
    """
    verts = []
    half = size / 2.0
    # Outer 4 vertices
    verts.extend([[-half, -half, 0.0], [half, -half, 0.0], [half, half, 0.0], [-half, half, 0.0]])
    # Inner circular hole (16 vertices)
    for i in range(n_inner):
        theta = 2.0 * math.pi * i / n_inner
        verts.append([hole_radius * math.cos(theta), hole_radius * math.sin(theta), 0.0])

    # An annular face or single 20-gon face
    face = [0, 1, 2, 3] + list(range(4, 4 + n_inner))
    return np.array(verts, dtype=float), [tuple(face)]


def create_spoke_starburst_mesh(size=4.0, hole_radius=0.5, n_pts=16):
    """Create a defective mesh exhibiting bicycle-spoke triangulation and radial needle slivers.
    Chords cut directly from outer 4 corners to inner circular knob vertices.
    """
    verts = []
    half = size / 2.0
    # 4 outer corners
    corners = [[-half, -half, 0.0], [half, -half, 0.0], [half, half, 0.0], [-half, half, 0.0]]
    verts.extend(corners)

    # Inner circular knob vertices
    inner_indices = []
    for i in range(n_pts):
        theta = 2.0 * math.pi * i / n_pts
        verts.append([hole_radius * math.cos(theta), hole_radius * math.sin(theta), 0.0])
        inner_indices.append(4 + i)

    # Fan spoke triangulation: each quadrant connects 1 outer corner to 4 inner vertices
    faces = []
    pts_per_quad = n_pts // 4
    for q in range(4):
        c_idx = q
        for k in range(pts_per_quad):
            i0 = (q * pts_per_quad + k) % n_pts
            i1 = (i0 + 1) % n_pts
            faces.append((c_idx, inner_indices[i0], inner_indices[i1]))
        # Bridge between adjacent corners
        next_c = (q + 1) % 4
        last_i = (q * pts_per_quad + pts_per_quad) % n_pts
        faces.append((c_idx, next_c, inner_indices[last_i]))

    return np.array(verts, dtype=float), faces


def create_barcode_slat_mesh(n_slats=10, width=10.0, height=0.1):
    """Generate a defective mesh with 1D collapsed quads (extreme aspect ratio slats).
    Matches the transverse dissolution failure mode.
    """
    verts = []
    for j in range(n_slats + 1):
        y = j * height
        verts.append([0.0, y, 0.0])
        verts.append([width, y, 0.0])

    faces = []
    for j in range(n_slats):
        v0 = j * 2
        v1 = j * 2 + 1
        v2 = (j + 1) * 2 + 1
        v3 = (j + 1) * 2
        faces.append((v0, v1, v2, v3))

    return np.array(verts, dtype=float), faces


def create_cracked_solid_box():
    """Create a box with a missing face, causing open boundary edges (boundary cracks)."""
    verts, faces = create_quad_box(sub_x=1, sub_y=1, sub_z=1)
    # Remove one face to introduce a boundary crack
    return verts, faces[:-1]


def create_high_valence_vertex_mesh(valence=12, radius=2.0):
    """Create a mesh containing a high-valence central vertex (e.g. 12 edges radiating)."""
    verts = [[0.0, 0.0, 0.0]]
    for i in range(valence):
        theta = 2.0 * math.pi * i / valence
        verts.append([radius * math.cos(theta), radius * math.sin(theta), 0.0])

    faces = []
    for i in range(valence):
        i_next = (i + 1) % valence
        faces.append((0, 1 + i, 1 + i_next))

    return np.array(verts, dtype=float), faces


def create_non_convex_chevron_mesh():
    """Create a defective chevron polygon / reflex triangle pair (>180 degrees)."""
    # Vertex at (1, 1), reflex interior vertex at (1.2, 0.5), outer vertices
    verts = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [1.0, 0.2, 0.0],  # Reflex indentation
            [2.0, 2.0, 0.0],
            [0.0, 2.0, 0.0],
        ],
        dtype=float,
    )
    # Triangle 1: (0, 1, 2), Triangle 2: (1, 3, 2)
    # Pairing them forms an invalid non-convex chevron quad
    faces = [(0, 1, 2), (1, 3, 2), (0, 2, 4), (2, 3, 4)]
    return verts, faces


def _weld_vertices(vertices, tol=1e-5):
    """Weld vertices within tol distance."""
    from scipy.spatial import cKDTree

    tree = cKDTree(vertices)
    unique_verts = []
    inv_map = {}
    visited = set()

    for idx, pt in enumerate(vertices):
        if idx in visited:
            continue
        nbrs = tree.query_ball_point(pt, r=tol)
        unique_idx = len(unique_verts)
        unique_verts.append(pt)
        for nbr in nbrs:
            visited.add(nbr)
            inv_map[nbr] = unique_idx

    return np.array(unique_verts, dtype=float), inv_map
