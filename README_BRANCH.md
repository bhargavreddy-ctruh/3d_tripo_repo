# Branch: `use-bpy-module-in-process` — Dead End

**Status:** Dead end. Superseded by `no-blender-pure-python`.

## What This Branch Tried

Run Blender in-process via the `bpy` pip module instead of launching a `blender` subprocess per pipeline stage. The goal was to eliminate the multi-second subprocess start-up overhead on each stage while keeping all existing `bmesh`/`bpy` code unchanged.

## Why It Failed

The `bpy` pip wheel version must exactly match the installed Blender desktop application version. Any Blender update (even a minor one) breaks the import with a cryptic ABI error. This creates an unacceptable maintenance burden for a production pipeline.

**Decision:** Instead of pinning Blender versions, we eliminated `bpy` entirely. See `no-blender-pure-python` for the milestone that achieved this.

## Key Commit

- `e256fa4` — Run Blender in-process via bpy module instead of per-stage subprocess

## Next Branch

→ [`no-blender-pure-python`](https://github.com/bhargavreddy-ctruh/3d_tripo_repo/tree/no-blender-pure-python) — eliminates the `bpy` dependency entirely.
