"""
evals/runner.py

Runs all 15 GridMind eval scenarios, scores each one, and writes
a timestamped results file to evals/results/.

Usage:
    python -m evals.runner                        # run all 15
    python -m evals.runner --scenario S02         # run one
    python -m evals.runner --scenario S02 S08     # run subset

Results are written to evals/results/run_<timestamp>.json
Pass rate is printed to stdout.
"""

import argparse
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Fix OpenMP conflict between PyTorch and FAISS on Windows
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.WARNING,      # suppress agent INFO logs during evals
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

from evals.scenarios import SCENARIO_MAP, SCENARIOS, FLEET_PRESETS


# ── Fleet management ──────────────────────────────────────────────────────────

def reset_fleet(seed: int = 42) -> None:
    """Regenerate fleet.json and history from scratch with a fixed seed."""
    from data.generate_fleet   import build_fleet, validate
    from data.generate_history import build_history
    from data.fleet_store      import FLEET_PATH, _fleet_cache, save_fleet
    import random
    from datetime import datetime, timezone

    fleet = build_fleet(seed=seed)
    validate(fleet)

    rng = random.Random(seed)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    for system in fleet:
        system["history"] = build_history(system, now, rng)

    # Clear cache and write
    import data.fleet_store as fs
    fs._fleet_cache = None
    save_fleet(fleet)

    # Clear escalations so previous sessions don't bleed into evals
    esc_path = fs.ESCALATIONS_PATH
    if esc_path.exists():
        esc_path.unlink()


def apply_preset(preset_name: str) -> None:
    """Apply anomaly overrides from a named preset to the current fleet."""
    if preset_name in ("as_is", "clean"):
        return

    import data.fleet_store as fs
    from data.fleet_store import save_fleet

    overrides = FLEET_PRESETS.get(preset_name, [])
    if not overrides:
        return

    fs._fleet_cache = None
    fleet = fs.load_fleet(force=True)
    fleet_map = {s["system_id"]: s for s in fleet}

    for override in overrides:
        sid = override["system_id"]
        if sid not in fleet_map:
            continue
        system = fleet_map[sid]
        for key, value in override.items():
            if key != "system_id" and key in system:
                system[key] = value

    save_fleet(fleet)
    fs._fleet_cache = None


# ── Scenario runner ───────────────────────────────────────────────────────────

def run_scenario(scenario) -> dict:
    """
    Execute one scenario and return a result dict.
    Handles both /chat-style (guardrail / direct) and full agent runs.
    """
    print(f"  Running {scenario.id}: {scenario.name} ...", end="", flush=True)
    start = time.time()

    # Prepare fleet
    if scenario.fleet_preset == "clean":
        reset_fleet()
    elif scenario.fleet_preset != "as_is":
        reset_fleet()
        apply_preset(scenario.fleet_preset)

    # Invalidate fleet_store cache before every run
    import data.fleet_store as fs
    fs._fleet_cache = None

    result = {
        "scenario_id":   scenario.id,
        "scenario_name": scenario.name,
        "prompt":        scenario.prompt,
        "fleet_preset":  scenario.fleet_preset,
        "passed":        False,
        "checks":        [],
        "elapsed":       0.0,
        "slow":          False,
        "error":         None,
        "resp":          None,
    }

    try:
        # Scenarios S10–S15 test the /chat intent router directly
        # Others test the full agent via run_session
        is_chat_scenario = len(scenario.expected_nodes) == 0

        if is_chat_scenario:
            # Call classify_intent + route directly (mirrors /chat endpoint logic)
            import os
            from anthropic import Anthropic
            import api.main as _main_module
            if not _main_module._anthropic.api_key:
                _main_module._anthropic = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
            from api.main import classify_intent
            from tools.registry import TOOL_MAP
            from data.fleet_store import load_escalations

            intent_data = classify_intent(scenario.prompt)
            intent      = intent_data.get("intent", "agent_run")

            if intent == "out_of_scope":
                resp = {
                    "type": "refusal",
                    "message": intent_data.get("refusal_reason", "Out of scope."),
                }
            elif intent == "show_anomalies":
                anomaly_type  = intent_data.get("anomaly_type")
                status_filter = intent_data.get("status_filter")
                STATUS_TO_ANOMALY = {"offline": "offline", "warning": "battery_drain", "degraded": None}
                if not anomaly_type and status_filter:
                    anomaly_type = STATUS_TO_ANOMALY.get(status_filter)
                data = TOOL_MAP["detect_anomalies"].invoke({"anomaly_type": anomaly_type, "threshold_pct": None})
                resp = {"type": "anomalies", "data": data}
            elif intent == "show_status":
                data = TOOL_MAP["get_fleet_summary"].invoke({})
                resp = {"type": "fleet_summary", "data": data}
            elif intent == "show_system":
                import re
                system_id = intent_data.get("system_id")
                if not system_id:
                    match = re.search(r"SYS_\d+", scenario.prompt.upper())
                    system_id = match.group(0) if match else "SYS_001"
                data = TOOL_MAP["get_system_status"].invoke({"system_id": system_id})
                resp = {"type": "system", "data": data}
            elif intent == "show_trends":
                metric = intent_data.get("metric") or "solar_output_kw"
                data   = TOOL_MAP["get_fleet_trends"].invoke({"hours_back": 24, "metric": metric})
                resp   = {"type": "trends", "data": data}
            elif intent == "show_escalations":
                data = load_escalations()
                resp = {"type": "escalations", "data": data}
            else:
                resp = {"type": "agent_run_needed"}

            result["resp"] = resp
            session = {}
            report  = resp

        else:
            # Full agent run
            from agent.runner import run_session
            report  = run_session(scenario.prompt, session_id=f"EVAL-{scenario.id}-{uuid.uuid4().hex[:6]}")
            session = report.get("session", {})
            resp    = report
            result["resp"] = report

        elapsed = time.time() - start
        result["elapsed"] = round(elapsed, 2)
        result["slow"]    = scenario.max_seconds is not None and elapsed > scenario.max_seconds

        # ── Evaluate outcome checks ───────────────────────────────────────────
        all_passed = True
        check_results = []

        for check_expr in scenario.outcome_checks:
            try:
                passed = bool(eval(check_expr, {
                    "report":  report,
                    "session": session,
                    "resp":    resp,
                }))
                check_results.append({"expr": check_expr, "passed": passed, "error": None})
                if not passed:
                    all_passed = False
            except Exception as e:
                check_results.append({"expr": check_expr, "passed": False, "error": str(e)})
                all_passed = False

        result["checks"] = check_results
        result["passed"] = all_passed

        status = "✓ PASS" if all_passed else "✗ FAIL"
        slow   = f" (slow: {elapsed:.1f}s)" if result["slow"] else f" ({elapsed:.1f}s)"
        print(f" {status}{slow}")

        if not all_passed:
            for c in check_results:
                if not c["passed"]:
                    err = f" — {c['error']}" if c["error"] else ""
                    print(f"    ✗ {c['expr']}{err}")

    except Exception as exc:
        elapsed = time.time() - start
        result["elapsed"] = round(elapsed, 2)
        result["error"]   = str(exc)
        result["passed"]  = False
        print(f" ✗ ERROR: {exc}")
        logger.exception("Scenario %s failed with exception", scenario.id)

    return result


# ── Main runner ───────────────────────────────────────────────────────────────

def run_all(scenario_ids: list[str] | None = None) -> None:
    scenarios = SCENARIOS
    if scenario_ids:
        scenarios = [SCENARIO_MAP[sid] for sid in scenario_ids if sid in SCENARIO_MAP]
        missing   = [sid for sid in scenario_ids if sid not in SCENARIO_MAP]
        if missing:
            print(f"Unknown scenario IDs: {missing}")
            sys.exit(1)

    print()
    print("═" * 64)
    print("  GridMind Eval Suite")
    print(f"  {len(scenarios)} scenario{'s' if len(scenarios) != 1 else ''} · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("═" * 64)
    print()

    results   = []
    run_start = time.time()

    for scenario in scenarios:
        result = run_scenario(scenario)
        results.append(result)

    total_elapsed = round(time.time() - run_start, 2)

    # ── Summary ───────────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    slow   = sum(1 for r in results if r["slow"])
    errors = sum(1 for r in results if r["error"])

    print()
    print("─" * 64)
    print(f"  Results:   {passed}/{len(results)} passed  ({round(passed/len(results)*100)}%)")
    print(f"  Failed:    {failed}")
    print(f"  Slow:      {slow}")
    print(f"  Errors:    {errors}")
    print(f"  Total time:{total_elapsed}s")
    print("─" * 64)

    if failed:
        print("\n  Failed scenarios:")
        for r in results:
            if not r["passed"]:
                print(f"    {r['scenario_id']} — {r['scenario_name']}")

    # ── Write results ─────────────────────────────────────────────────────────
    timestamp   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS_DIR / f"run_{timestamp}.json"

    run_record = {
        "run_id":        f"RUN_{timestamp}",
        "ran_at":        datetime.now(timezone.utc).isoformat(),
        "total_elapsed": total_elapsed,
        "total":         len(results),
        "passed":        passed,
        "failed":        failed,
        "pass_rate_pct": round(passed / len(results) * 100, 1),
        "scenarios":     results,
    }

    # Strip large report data before saving to keep files manageable
    for r in run_record["scenarios"]:
        if isinstance(r.get("resp"), dict) and "history" in str(r["resp"])[:100]:
            r["resp"] = {"truncated": True}

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(run_record, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n  Results written → {output_path}")
    print()

    # Exit with non-zero if any failures — useful in CI
    if failed:
        sys.exit(1)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run GridMind eval scenarios.")
    parser.add_argument(
        "--scenario", "-s",
        nargs="+",
        default=None,
        help="Scenario ID(s) to run (e.g. S01 S02). Omit to run all 15.",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all scenarios and exit.",
    )
    args = parser.parse_args()

    if args.list:
        print(f"\n{'ID':<6} {'Name':<45} {'Preset':<22} {'Checks'}")
        print("─" * 90)
        for s in SCENARIOS:
            print(f"{s.id:<6} {s.name:<45} {s.fleet_preset:<22} {len(s.outcome_checks)}")
        print()
        sys.exit(0)

    run_all(args.scenario)