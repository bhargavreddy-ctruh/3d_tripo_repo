"""Binary paths and tunables for the vacuum_quad_engine pipeline.

No fixed face-count target lives here (see PROGRESS.md/TECH_NOTES.md,
"Primary objective"). Angular thresholds are scale-independent and may be
fixed constants; any distance/length tolerance must be derived from a
mesh's own scale (bounding-box diagonal) at the call site, not hardcoded
here as an absolute unit.
"""

import os
import shutil

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ENGINE_ROOT = os.path.dirname(_THIS_DIR)

# ---------------------------------------------------------------------------
# Binaries
# ---------------------------------------------------------------------------
#
# No Blender dependency: this pipeline is pure Python (EditMesh/io_mesh,
# trimesh, igl) end to end — see io_mesh.py's docstring. The only external
# binaries left are the field-aligned remeshers below (FBX input is not
# supported by this backend; pre-convert to .obj/.glb first).

# Instant Meshes found on this machine; known to have crashed repeatedly in
# GUI mode previously (see ~/Library/Logs/DiagnosticReports), but the CLI
# batch-mode invocation (`-o ... -f ...`, no GUI) tested clean on 2026-11-01.
# quadriflow is the already-proven, stable fallback used successfully in
# tripo-logic-approach-v2.
INSTANT_MESHES_CANDIDATES = [
    os.path.join(_ENGINE_ROOT, "bin", "instant_meshes"),   # bundled in the repo (bin/)
    os.path.join(_ENGINE_ROOT, "bin", "instant-meshes"),
    "/Applications/Instant Meshes.app/Contents/MacOS/Instant Meshes",
    "instant-meshes",
]

QUADRIFLOW_CANDIDATES = [
    os.path.join(_ENGINE_ROOT, "bin", "quadriflow"),
    "quadriflow",
]


def _first_existing(candidates):
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
        found = shutil.which(c)
        if found:
            return found
    return None


INSTANT_MESHES_BIN = _first_existing(INSTANT_MESHES_CANDIDATES)
QUADRIFLOW_BIN = _first_existing(QUADRIFLOW_CANDIDATES)

# Which remesher backend remesh.py prefers when both are available.
# "instant_meshes" gives the 4-RoSy/4-PoSy dominant-quad mode tripo_smart_engine
# relies on; "quadriflow" is the already-battle-tested fallback.
DEFAULT_REMESH_BACKEND = "instant_meshes" if INSTANT_MESHES_BIN else "quadriflow"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ASSETS_INPUTS_DIR = os.path.join(_ENGINE_ROOT, "assets", "inputs")
BENCHMARKS_DIR = os.path.join(_ENGINE_ROOT, "benchmarks")
REPORTS_DIR = os.path.join(_ENGINE_ROOT, "reports")

# ---------------------------------------------------------------------------
# Tunables (angles only — scale-independent; no absolute-unit constants here)
# ---------------------------------------------------------------------------

CREASE_DEG = 18.0            # dihedral angle above which an edge is always a crease
TIER1_FLAT_DEG = 3.0         # below this, a face pair is "ultra-flat"
MICRO_FEATURE_CURVE_DEG = 12.0   # curvature angle threshold for the micro-feature rule
MICRO_FEATURE_AREA_FRAC = 0.15   # fraction of LOCAL (per-component) median face area
DOME_SADDLE_DEG = 28.0       # mean face-normal deviation threshold for pole/dome vertices
COPLANAR_DART_DEG = 24.0     # triangle-pair coplanarity threshold for dart merging
PLANAR_STRAIGHTEN_DEG = 3.0  # lattice-straightening coplanarity gate


def validate_environment():
    """Raise RuntimeError listing anything missing, else return True."""
    missing = []
    if not INSTANT_MESHES_BIN and not QUADRIFLOW_BIN:
        missing.append("Instant Meshes or quadriflow (need at least one remesher)")
    try:
        import trimesh, igl, numpy  # noqa: F401  (presence check only)
    except ImportError as e:
        missing.append(f"a required pure-Python dependency ({e})")
    if missing:
        raise RuntimeError(f"Missing required binaries: {', '.join(missing)}")
    return True


if __name__ == "__main__":
    print("INSTANT_MESHES_BIN =", INSTANT_MESHES_BIN)
    print("QUADRIFLOW_BIN     =", QUADRIFLOW_BIN)
    print("DEFAULT_REMESH_BACKEND =", DEFAULT_REMESH_BACKEND)
    validate_environment()
    print("Environment OK.")
