"""CLI entry point for running mocharpa pipelines.

Usage::

    python -m mocharpa run pipeline.yaml
    python -m mocharpa run pipeline.json --driver playwright --verbose
    python -m mocharpa run pipeline.yaml --dry-run
    python -m mocharpa validate pipeline.yaml
    python -m mocharpa init myproject
    python -m mocharpa schedule add --name daily --cron "0 9 * * 1-5" pipeline.yaml
    python -m mocharpa schedule start
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _parse_data(raw: list[str]) -> Dict[str, Any]:
    """Parse ``--data key=value`` pairs into a dict."""
    result: Dict[str, Any] = {}
    for item in raw:
        if "=" not in item:
            raise argparse.ArgumentTypeError(f"Expected key=value, got: {item}")
        k, v = item.split("=", 1)
        if v.isdigit():
            v = int(v)
        elif v.replace(".", "", 1).isdigit():
            try:
                v = float(v)
            except ValueError:
                pass
        elif v.lower() in ("true", "false"):
            v = v.lower() == "true"
        elif v.lower() == "null":
            v = None
        result[k] = v
    return result


def _create_context(driver_type: str, verbose: bool):
    """Create an AutomationContext with the requested driver."""
    logger = logging.getLogger("mocharpa")
    if driver_type == "mock":
        from mocharpa.drivers.mock_driver import MockDriver
        from mocharpa.core.context import AutomationContext

        driver = MockDriver()
        driver.connect()
        logger.info("Using MockDriver")
        return AutomationContext(timeout=30, driver=driver)
    elif driver_type == "playwright":
        try:
            from mocharpa.drivers.playwright_driver import PlaywrightDriver
            from mocharpa.core.context import AutomationContext
        except ImportError:
            print(
                "Playwright driver requires 'playwright' package.\n"
                "Install with: pip install mocharpa[browser]",
                file=sys.stderr,
            )
            sys.exit(1)
        driver = PlaywrightDriver(headless=True)
        driver.connect()
        logger.info("Using PlaywrightDriver (headless)")
        return AutomationContext(timeout=30, driver=driver)
    else:
        print(f"Unknown driver: {driver_type}", file=sys.stderr)
        sys.exit(1)


def _load_pipeline(filepath: Path):
    """Load a pipeline from file, supporting YAML and JSON."""
    suffix = filepath.suffix.lower()
    if suffix in (".yaml", ".yml"):
        from mocharpa.pipeline.loader import load_yaml_file
        return load_yaml_file(filepath)
    elif suffix == ".json":
        from mocharpa.pipeline.loader import load_json_file
        return load_json_file(filepath)
    else:
        print(
            f"Unsupported format: {suffix}.  Supported: .yaml, .yml, .json",
            file=sys.stderr,
        )
        sys.exit(1)


# ======================================================================
# run
# ======================================================================

def cmd_run(args: argparse.Namespace) -> None:
    """Run a pipeline from file."""
    _setup_logging(args.verbose)
    logger = logging.getLogger("mocharpa")

    filepath = Path(args.file)
    if not filepath.exists():
        print(f"File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    pipeline = _load_pipeline(filepath)

    # Dry-run: validate and exit
    if args.dry_run:
        print(f"Dry-run: {pipeline.name or filepath.name}")
        print(f"  Steps:  {len(pipeline._steps)}")
        for i, step in enumerate(pipeline._steps):
            flags = []
            if getattr(step, "_condition", None):
                flags.append("conditional")
            if step.continue_on_error:
                flags.append("continue_on_error")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            print(f"  [{i}] {step.name}{flag_str}")
        print("  (no actions executed)")
        # Also validate schema
        import json
        try:
            import yaml
            data = yaml.safe_load(filepath.read_text(encoding="utf-8"))
        except ImportError:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        from mocharpa.pipeline.validator import validate_pipeline
        errors = validate_pipeline(data)
        if errors:
            print(f"\n  Validation warnings ({len(errors)}):")
            for e in errors:
                print(f"    - {e}")
        else:
            print("\n  Validation: OK")
        return

    # Create context
    ctx = _create_context(args.driver, args.verbose)
    initial_data = _parse_data(args.data) if args.data else {}

    logger.info("Running pipeline: %s (driver=%s, steps=%d)",
                pipeline.name or filepath.name, args.driver, len(pipeline._steps))

    # Run with pipeline-level retry and audit
    result = pipeline.run(
        data=initial_data,
        context=ctx,
        retry_count=args.retry_count,
        retry_delay=args.retry_delay,
        audit=args.audit,
    )

    # Output
    print()
    print(f"Pipeline: {pipeline.name or filepath.name}")
    print(f"  Status:  {'OK' if result.success else 'FAILED'}")
    print(f"  Steps:   {len(result.step_results)} completed, "
          f"{len(result.skipped)} skipped, {len(result.errors)} errors")
    print(f"  Elapsed: {result.elapsed:.2f}s")

    if result.step_results:
        print("\nStep results:")
        for name, value in result.step_results.items():
            if isinstance(value, str) and len(value) > 80:
                value = value[:77] + "..."
            print(f"  {name}: {value}")

    if result.errors:
        print("\nErrors:")
        for name, msg in result.errors.items():
            print(f"  {name}: {msg}")

    if result.skipped:
        print(f"\nSkipped: {', '.join(result.skipped)}")

    # Audit output
    if args.audit and hasattr(result, "audit") and result.audit:
        if args.audit_output:
            audit_path = Path(args.audit_output)
            audit_path.write_text(result.audit.to_json(), encoding="utf-8")
            print(f"\nAudit saved to: {audit_path}")
        else:
            print(f"\nAudit summary: {result.audit.summary()}")

    # Cleanup
    if hasattr(ctx, 'driver') and ctx.driver:
        ctx.driver.disconnect()

    sys.exit(0 if result.success else 1)


# ======================================================================
# validate
# ======================================================================

def cmd_validate(args: argparse.Namespace) -> None:
    """Validate a pipeline definition file."""
    filepath = Path(args.file)
    if not filepath.exists():
        print(f"File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    suffix = filepath.suffix.lower()
    if suffix in (".yaml", ".yml"):
        import yaml
        data = yaml.safe_load(filepath.read_text(encoding="utf-8"))
    elif suffix == ".json":
        import json
        data = json.loads(filepath.read_text(encoding="utf-8"))
    else:
        print(f"Unsupported format: {suffix}", file=sys.stderr)
        sys.exit(1)

    from mocharpa.pipeline.validator import validate_pipeline
    errors = validate_pipeline(data)

    if errors:
        print(f"Validation errors ({len(errors)}):")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print(f"Pipeline '{filepath.name}' is valid.")
        sys.exit(0)


# ======================================================================
# init
# ======================================================================

def cmd_init(args: argparse.Namespace) -> None:
    """Scaffold a new mocharpa project directory."""
    project_dir = Path(args.directory)
    project_dir.mkdir(parents=True, exist_ok=True)

    pipeline_file = project_dir / "pipeline.yaml"
    if not pipeline_file.exists():
        pipeline_file.write_text("""\
# Mocharpa pipeline definition
# Run with: mocharpa run pipeline.yaml

pipeline:
  name: example_pipeline
  steps:
    # Example step — replace with your own actions
    - name: hello_world
      action: transform
      fn: identity  # placeholder
""", encoding="utf-8")
        print(f"Created: {pipeline_file}")

    config_file = project_dir / "mocharpa.yaml"
    if not config_file.exists():
        config_file.write_text("""\
# Mocharpa configuration
default_profile: default

profiles:
  default:
    driver: mock
    timeout: 30.0
    retry_count: 3
    retry_delay: 0.5

  # Example production profile with Playwright
  # prod:
  #   driver: playwright
  #   headless: true
  #   browser_type: chromium
  #   timeout: 60.0
  #   database:
  #     url: sqlite:///data.db
  #   http:
  #     base_url: https://api.example.com
  #     headers:
  #       Authorization: "Bearer ${env.API_TOKEN}"
""", encoding="utf-8")
        print(f"Created: {config_file}")

    print(f"\nProject initialized in: {project_dir}")
    print("Next steps:")
    print(f"  1. Edit {pipeline_file}")
    print(f"  2. Run with: mocharpa run {pipeline_file}")
    sys.exit(0)


# ======================================================================
# schedule
# ======================================================================

def cmd_schedule_add(args: argparse.Namespace) -> None:
    """Add a scheduled pipeline."""
    from mocharpa.scheduler import Schedule, Scheduler

    filepath = Path(args.file)
    if not filepath.exists():
        print(f"File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    data = _parse_data(args.data) if args.data else {}

    sched = Schedule(
        name=args.name,
        cron=args.cron,
        pipeline=str(filepath.resolve()),
        driver=args.driver,
        data=data,
    )

    scheduler = Scheduler()
    scheduler.add(sched)
    print(f"Schedule '{args.name}' added (cron={args.cron}, driver={args.driver})")
    print("Start the scheduler with: mocharpa schedule start")


def cmd_schedule_remove(args: argparse.Namespace) -> None:
    """Remove a scheduled pipeline."""
    from mocharpa.scheduler import Scheduler

    scheduler = Scheduler()
    removed = scheduler.remove(args.name)
    if removed:
        print(f"Schedule '{args.name}' removed.")
    else:
        print(f"Schedule '{args.name}' not found.", file=sys.stderr)
        sys.exit(1)


def cmd_schedule_list(args: argparse.Namespace) -> None:
    """List all scheduled pipelines."""
    from mocharpa.scheduler import Scheduler

    scheduler = Scheduler()
    schedules = scheduler.list_all()
    if not schedules:
        print("No schedules registered.")
        return

    print(f"Schedules ({len(schedules)}):")
    for s in schedules:
        status = "enabled" if s.enabled else "disabled"
        last = s.last_run.strftime("%Y-%m-%d %H:%M") if s.last_run else "never"
        print(f"  {s.name}")
        print(f"    cron:   {s.cron}")
        print(f"    file:   {s.pipeline}")
        print(f"    driver: {s.driver}")
        print(f"    status: {status}, last_run: {last}")


def cmd_schedule_start(args: argparse.Namespace) -> None:
    """Start the scheduler loop."""
    from mocharpa.scheduler import Scheduler

    scheduler = Scheduler()
    schedules = scheduler.list_all()
    if not schedules:
        print("No schedules registered. Add one first:")
        print("  mocharpa schedule add --name daily --cron '0 9 * * *' pipeline.yaml")
        sys.exit(1)

    scheduler.start()
    print(f"Scheduler started with {len(schedules)} schedule(s). Ctrl+C to stop.")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping scheduler...")
        scheduler.stop()
        print("Scheduler stopped.")


def cmd_schedule_run(args: argparse.Namespace) -> None:
    """Run a named schedule immediately."""
    from mocharpa.scheduler import Scheduler

    scheduler = Scheduler()
    ok = scheduler.run_once(args.name)
    if ok:
        print(f"Schedule '{args.name}' completed successfully.")
    else:
        print(f"Schedule '{args.name}' failed or not found.", file=sys.stderr)
        sys.exit(1)


# ======================================================================
# main
# ======================================================================

def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mocharpa",
        description="Mocharpa RPA framework — run automation pipelines.",
    )
    sub = parser.add_subparsers(title="commands", dest="command")

    # -- run ----------------------------------------------------------------
    p_run = sub.add_parser("run", help="Run a pipeline from a YAML/JSON file")
    p_run.add_argument("file", help="Path to pipeline .yaml or .json file")
    p_run.add_argument(
        "--driver", default="mock", choices=["mock", "playwright"],
        help="Driver backend (default: mock)",
    )
    p_run.add_argument(
        "--data", nargs="*", metavar="KEY=VALUE",
        help="Initial data pairs (e.g. --data env=prod user=admin)",
    )
    p_run.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    p_run.add_argument(
        "--dry-run", action="store_true",
        help="Validate and list steps without executing",
    )
    p_run.add_argument(
        "--retry-count", type=int, default=0,
        help="Pipeline-level retry count (default: 0)",
    )
    p_run.add_argument(
        "--retry-delay", type=float, default=1.0,
        help="Seconds between pipeline-level retries (default: 1.0)",
    )
    p_run.add_argument(
        "--audit", action="store_true",
        help="Enable structured audit recording",
    )
    p_run.add_argument(
        "--audit-output",
        help="Save audit record as JSON to this path",
    )
    p_run.set_defaults(handler=cmd_run)

    # -- validate -----------------------------------------------------------
    p_val = sub.add_parser("validate", help="Validate a pipeline definition")
    p_val.add_argument("file", help="Path to pipeline .yaml or .json file")
    p_val.set_defaults(handler=cmd_validate)

    # -- init ---------------------------------------------------------------
    p_init = sub.add_parser("init", help="Scaffold a new mocharpa project")
    p_init.add_argument("directory", nargs="?", default=".", help="Project directory (default: .)")
    p_init.set_defaults(handler=cmd_init)

    # -- schedule -----------------------------------------------------------
    p_sched = sub.add_parser("schedule", help="Manage scheduled pipelines")
    sched_sub = p_sched.add_subparsers(title="schedule_commands", dest="schedule_command")

    p_add = sched_sub.add_parser("add", help="Add a scheduled pipeline")
    p_add.add_argument("--name", required=True, help="Unique schedule name")
    p_add.add_argument("--cron", required=True, help="5-field cron expression")
    p_add.add_argument("--file", required=True, help="Path to pipeline file")
    p_add.add_argument("--driver", default="mock", choices=["mock", "playwright"])
    p_add.add_argument("--data", nargs="*", metavar="KEY=VALUE")
    p_add.set_defaults(handler=cmd_schedule_add)

    p_rm = sched_sub.add_parser("remove", help="Remove a scheduled pipeline")
    p_rm.add_argument("--name", required=True, help="Schedule name to remove")
    p_rm.set_defaults(handler=cmd_schedule_remove)

    p_list = sched_sub.add_parser("list", help="List all scheduled pipelines")
    p_list.set_defaults(handler=cmd_schedule_list)

    p_start = sched_sub.add_parser("start", help="Start the scheduler loop")
    p_start.set_defaults(handler=cmd_schedule_start)

    p_run_sched = sched_sub.add_parser("run", help="Run a named schedule immediately")
    p_run_sched.add_argument("--name", required=True, help="Schedule name to run")
    p_run_sched.set_defaults(handler=cmd_schedule_run)

    # Default: show help
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    args.handler(args)


if __name__ == "__main__":
    main()
