#!/usr/bin/env python3
"""CLI entry point for the generalized retopology pipeline."""
import os
import sys

# Ensure core is on the module search path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "core"))
import pipeline


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 run_pipeline.py <input_mesh.(obj|glb|gltf)> <output_directory> [max_dissolve_passes]")
        sys.exit(1)
    input_path = sys.argv[1]
    output_dir = sys.argv[2]
    max_passes = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    report = pipeline.run_pipeline(input_path, output_dir, max_dissolve_passes=max_passes)
    return report


if __name__ == "__main__":
    main()
