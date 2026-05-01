"""CLI entry point for running mocharpa pipelines.

Usage::

    python -m mocharpa run pipeline.yaml
    python -m mocharpa run pipeline.json --driver mock --verbose
    mocharpa run pipeline.yaml --data env=prod
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional


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
        # Try numeric conversion
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
            from mocharpa.plugins.browser.driver import PlaywrightDriver
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


def cmd_run(args: argparse.Namespace) -> None:
    """Run a pipeline from file."""
    _setup_logging(args.verbose)
    logger = logging.getLogger("mocharpa")

    filepath = Path(args.file)
    if not filepath.exists():
        print(f"File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    suffix = filepath.suffix.lower()

    # Load pipeline
    if suffix in (".yaml", ".yml"):
        from mocharpa.pipeline.loader import load_yaml_file
        pipeline = load_yaml_file(filepath)
    elif suffix == ".json":
        from mocharpa.pipeline.loader import load_json_file
        pipeline = load_json_file(filepath)
    else:
        print(
            f"Unsupported format: {suffix}.  Supported: .yaml, .yml, .json",
            file=sys.stderr,
        )
        sys.exit(1)

    # Create context
    ctx = _create_context(args.driver, args.verbose)
    initial_data = _parse_data(args.data) if args.data else {}

    logger.info("Running pipeline: %s (driver=%s, steps=%d)",
                pipeline.name or filepath.name, args.driver, len(pipeline._steps))

    # Run
    result = pipeline.run(data=initial_data, context=ctx)

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

    # Cleanup
    if hasattr(ctx, 'driver') and ctx.driver:
        ctx.driver.disconnect()

    sys.exit(0 if result.success else 1)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mocharpa",
        description="Mocharpa RPA framework — run automation pipelines.",
    )
    sub = parser.add_subparsers(title="commands", dest="command")

    # run
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
    p_run.set_defaults(handler=cmd_run)

    # Default: show help
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    args.handler(args)


if __name__ == "__main__":
    main()
