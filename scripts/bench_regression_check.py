"""Benchmark regression gate.

Parses the output of scripts/bench_http.py, compares per-scenario RPS
against stored baselines in docs/bench_baselines.json, and exits non-zero
if any scenario regresses beyond the allowed tolerance.

Usage
-----
python scripts/bench_regression_check.py \
    --results /tmp/bench_output.txt \
    --baselines docs/bench_baselines.json \
    --tolerance 0.15          # allow up to 15% regression before failing
"""

import argparse
import json
import re
import sys
from pathlib import Path

SCENARIO_HEADER_RE = re.compile(r"^\[(.+)\]$")
RPS_LINE_RE = re.compile(r"^\s*rps\s*=\s*([0-9.]+)")
OK_LINE_RE = re.compile(r"^\s*ok\s*=\s*([0-9]+)")
ERRORS_LINE_RE = re.compile(r"^\s*errors\s*=\s*([0-9]+)")
AGGREGATE_HEADER = "[aggregate]"


def parse_bench_output(text: str) -> dict[str, dict[str, float]]:
    """Parse bench_http.py stdout into {scenario_name: {rps, ok, errors}}."""
    results: dict[str, dict[str, float]] = {}
    current_scenario: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        header_match = SCENARIO_HEADER_RE.match(line)
        if header_match:
            current_scenario = header_match.group(1)
            assert current_scenario is not None
            results[current_scenario] = {}
            continue

        if current_scenario is None:
            continue

        rps_match = RPS_LINE_RE.match(line)
        if rps_match:
            results[current_scenario]["rps"] = float(rps_match.group(1))
            continue

        ok_match = OK_LINE_RE.match(line)
        if ok_match:
            results[current_scenario]["ok"] = float(ok_match.group(1))
            continue

        errors_match = ERRORS_LINE_RE.match(line)
        if errors_match:
            results[current_scenario]["errors"] = float(errors_match.group(1))
            continue

    return results


def check_regression(
    measured: dict[str, dict[str, float]],
    baselines: dict[str, dict[str, float]],
    tolerance: float,
) -> list[str]:
    """Return a list of failure messages; empty list means all pass."""
    failures: list[str] = []

    for scenario_name, baseline_metrics in baselines.items():
        if scenario_name.startswith("_"):
            continue  # skip metadata/comment keys
        if scenario_name not in measured:
            failures.append(f"MISSING scenario in output: '{scenario_name}'")
            continue

        measured_metrics = measured[scenario_name]

        baseline_rps = baseline_metrics.get("rps", 0.0)
        measured_rps = measured_metrics.get("rps", 0.0)
        min_acceptable_rps = baseline_rps * (1.0 - tolerance)

        if measured_rps < min_acceptable_rps:
            regression_pct = (baseline_rps - measured_rps) / baseline_rps * 100
            failures.append(
                f"REGRESSION [{scenario_name}]: "
                f"rps={measured_rps:.2f} is {regression_pct:.1f}% below baseline "
                f"rps={baseline_rps:.2f} (tolerance={tolerance*100:.0f}%)"
            )

        baseline_errors = baseline_metrics.get("max_errors", None)
        if baseline_errors is not None:
            measured_errors = measured_metrics.get("errors", 0.0)
            if measured_errors > baseline_errors:
                failures.append(
                    f"ERROR SPIKE [{scenario_name}]: "
                    f"errors={int(measured_errors)} exceeds baseline max_errors={int(baseline_errors)}"
                )

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark regression gate")
    parser.add_argument("--results", required=True, help="Path to bench_http.py stdout")
    parser.add_argument("--baselines", required=True, help="Path to bench_baselines.json")
    parser.add_argument(
        "--tolerance", type=float, default=0.15, help="Allowed RPS regression fraction (default 0.15 = 15%%)"
    )
    args = parser.parse_args()

    results_text = Path(args.results).read_text()
    baselines: dict[str, dict[str, float]] = json.loads(Path(args.baselines).read_text())

    measured = parse_bench_output(results_text)

    print("\n=== Benchmark Regression Check ===")
    print(f"Tolerance: {args.tolerance*100:.0f}%\n")

    for scenario, metrics in measured.items():
        rps = metrics.get("rps", 0.0)
        ok = int(metrics.get("ok", 0))
        errors = int(metrics.get("errors", 0))
        baseline_rps = baselines.get(scenario, {}).get("rps", None)
        baseline_str = f"  baseline_rps={baseline_rps:.2f}" if baseline_rps is not None else "  (no baseline)"
        print(f"  [{scenario}]  rps={rps:.2f}  ok={ok}  errors={errors}{baseline_str}")

    failures = check_regression(measured, baselines, args.tolerance)

    if failures:
        print("\n[FAILED] Regression detected:")
        for failure in failures:
            print(f"  ✗ {failure}")
        sys.exit(1)
    else:
        print("\n[PASSED] All scenarios within tolerance.")
        sys.exit(0)


if __name__ == "__main__":
    main()
