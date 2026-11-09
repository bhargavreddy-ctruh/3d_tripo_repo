#!/usr/bin/env python3
"""Unified Test Runner for Pure-Python Mesh Processing Pipeline E2E Test Suite.

Discovers and executes tests across the 4 validation tiers:
- Tier 1: Feature Coverage (Quad Grids, Planar Faces, Internal Holes, Curved Surfaces, Boundary Loops)
- Tier 2: Boundary & Corner Cases (Empty mesh, Single quad/tri, Non-convex polygons, High-valence, Collinear, Extreme AR)
- Tier 3: Cross-Feature Combinations (Holes on curved surfaces, Multiple knobs on planar panel, Concentric rings, Assemblies)
- Tier 4: Real-World Benchmark Workloads (woodenrack_854k, 002, sofa_860k, parumala_thirumeni, forensic legacy audits)

Usage:
    python3 tests/test_runner.py [--tier 1|2|3|4|all] [--verbose] [--json-output report.json]
"""

import argparse
import io
import json
import os
import sys
import time
import unittest

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

def get_tier_map():
    """Lazily load test classes to avoid double discovery under unittest discover."""
    from tests.test_tier1_features import (
        TestTier1QuadGrids,
        TestTier1PlanarFaces,
        TestTier1InternalHoles,
        TestTier1CurvedSurfaces,
        TestTier1BoundaryLoops,
    )
    from tests.test_tier2_boundaries import (
        TestTier2EmptyAndMinimalMeshes,
        TestTier2NonConvexPolygons,
        TestTier2HighValenceVertices,
        TestTier2CollinearAndDegenerate,
        TestTier2ExtremeAspectRatios,
    )
    from tests.test_tier3_combinations import (
        TestTier3HolesOnCurvedSurfaces,
        TestTier3MultipleHolesPlanar,
        TestTier3ConcentricFeatures,
        TestTier3AssembliesAndBoundaries,
    )
    from tests.test_tier4_workloads import (
        TestTier4BenchmarkAssets,
        TestTier4LegacyFailureDetections,
        TestTier4ProductionOutputHarness,
    )

    return {
        1: [
            TestTier1QuadGrids,
            TestTier1PlanarFaces,
            TestTier1InternalHoles,
            TestTier1CurvedSurfaces,
            TestTier1BoundaryLoops,
        ],
        2: [
            TestTier2EmptyAndMinimalMeshes,
            TestTier2NonConvexPolygons,
            TestTier2HighValenceVertices,
            TestTier2CollinearAndDegenerate,
            TestTier2ExtremeAspectRatios,
        ],
        3: [
            TestTier3HolesOnCurvedSurfaces,
            TestTier3MultipleHolesPlanar,
            TestTier3ConcentricFeatures,
            TestTier3AssembliesAndBoundaries,
        ],
        4: [
            TestTier4BenchmarkAssets,
            TestTier4LegacyFailureDetections,
            TestTier4ProductionOutputHarness,
        ],
    }

TIER_NAMES = {
    1: "Tier 1: Feature Coverage",
    2: "Tier 2: Boundary & Corner Cases",
    3: "Tier 3: Cross-Feature Combinations",
    4: "Tier 4: Real-World Benchmark Workloads",
}


class StructuredTestResult(unittest.TestResult):
    """Custom TestResult that captures structured execution data per test."""

    def __init__(self):
        super().__init__()
        self.test_records = []
        self._current_start = None

    def startTest(self, test):
        super().startTest(test)
        self._current_start = time.time()

    def addSuccess(self, test):
        super().addSuccess(test)
        elapsed = time.time() - (self._current_start or time.time())
        self.test_records.append({
            "test_id": test.id(),
            "name": test._testMethodName,
            "class": test.__class__.__name__,
            "status": "PASS",
            "duration_sec": round(elapsed, 4),
            "error": None,
        })

    def addFailure(self, test, err):
        super().addFailure(test, err)
        elapsed = time.time() - (self._current_start or time.time())
        self.test_records.append({
            "test_id": test.id(),
            "name": test._testMethodName,
            "class": test.__class__.__name__,
            "status": "FAIL",
            "duration_sec": round(elapsed, 4),
            "error": self._format_err(err),
        })

    def addError(self, test, err):
        super().addError(test, err)
        elapsed = time.time() - (self._current_start or time.time())
        self.test_records.append({
            "test_id": test.id(),
            "name": test._testMethodName,
            "class": test.__class__.__name__,
            "status": "ERROR",
            "duration_sec": round(elapsed, 4),
            "error": self._format_err(err),
        })

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        elapsed = time.time() - (self._current_start or time.time())
        self.test_records.append({
            "test_id": test.id(),
            "name": test._testMethodName,
            "class": test.__class__.__name__,
            "status": "SKIP",
            "duration_sec": round(elapsed, 4),
            "error": reason,
        })

    def _format_err(self, err):
        import traceback
        exctype, value, tb = err
        return "".join(traceback.format_exception(exctype, value, tb))


def run_tier(tier_num, test_classes, verbose=False):
    """Run tests for a single tier and return structured results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    result = StructuredTestResult()
    start_time = time.time()
    suite.run(result)
    total_time = time.time() - start_time

    return {
        "tier": tier_num,
        "name": TIER_NAMES.get(tier_num, f"Tier {tier_num}"),
        "total_tests": result.testsRun,
        "passed": len([r for r in result.test_records if r["status"] == "PASS"]),
        "failed": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "duration_sec": round(total_time, 4),
        "records": result.test_records,
    }


def main():
    parser = argparse.ArgumentParser(description="Mesh Processing Pipeline E2E Test Suite Runner")
    parser.add_argument("--tier", default="all", choices=["1", "2", "3", "4", "all"], help="Tier to execute (default: all)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print verbose test results")
    parser.add_argument("--json-output", type=str, default=None, help="File path to save JSON test results")

    args = parser.parse_args()

    selected_tiers = [1, 2, 3, 4] if args.tier == "all" else [int(args.tier)]
    tier_map = get_tier_map()

    print("=" * 80)
    print("MESH PROCESSING PIPELINE E2E TEST SUITE RUNNER")
    print(f"Executing Tiers: {[TIER_NAMES[t] for t in selected_tiers]}")
    print("=" * 80)

    overall_start = time.time()
    tier_results = []
    total_run = 0
    total_passed = 0
    total_failed = 0
    total_errors = 0
    total_skipped = 0

    for t in selected_tiers:
        print(f"\n>>> Running {TIER_NAMES[t]} ({len(tier_map[t])} test classes)...")
        res = run_tier(t, tier_map[t], verbose=args.verbose)
        tier_results.append(res)

        total_run += res["total_tests"]
        total_passed += res["passed"]
        total_failed += res["failed"]
        total_errors += res["errors"]
        total_skipped += res["skipped"]

        if args.verbose:
            for rec in res["records"]:
                status_symbol = "[PASS]" if rec["status"] == "PASS" else f"[{rec['status']}]"
                print(f"  {status_symbol} {rec['class']}::{rec['name']} ({rec['duration_sec']}s)")
                if rec["error"] and rec["status"] in ("FAIL", "ERROR"):
                    print(f"      {rec['error'].strip()}")

        status_str = "OK" if (res["failed"] == 0 and res["errors"] == 0) else "FAILED"
        print(f"    Result: {status_str} — {res['passed']}/{res['total_tests']} passed ({res['duration_sec']}s)")

    overall_time = time.time() - overall_start

    print("\n" + "=" * 80)
    print("E2E TEST SUITE EXECUTION SUMMARY")
    print("=" * 80)
    for res in tier_results:
        t_status = "PASS" if (res["failed"] == 0 and res["errors"] == 0) else "FAIL"
        print(
            f"  [{t_status}] {res['name']:<40} : "
            f"{res['passed']:>2}/{res['total_tests']:<2} passed, "
            f"{res['failed']} failed, {res['skipped']} skipped ({res['duration_sec']}s)"
        )

    print("-" * 80)
    final_success = (total_failed == 0 and total_errors == 0)
    summary_status = "ALL TESTS PASSED [100% OK]" if final_success else "TEST SUITE FAILED"
    print(f"Final Status:      {summary_status}")
    print(f"Total Tests Run:   {total_run}")
    print(f"Total Passed:      {total_passed}")
    print(f"Total Failed:      {total_failed}")
    print(f"Total Errors:      {total_errors}")
    print(f"Total Skipped:     {total_skipped}")
    print(f"Total Time:        {overall_time:.3f} seconds")
    print("=" * 80)

    if args.json_output:
        report_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "overall_status": "PASS" if final_success else "FAIL",
            "total_run": total_run,
            "total_passed": total_passed,
            "total_failed": total_failed,
            "total_errors": total_errors,
            "total_skipped": total_skipped,
            "total_time_sec": round(overall_time, 4),
            "tiers": tier_results,
        }
        with open(args.json_output, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
        print(f"Structured test report written to: {args.json_output}")

    sys.exit(0 if final_success else 1)


if __name__ == "__main__":
    main()
