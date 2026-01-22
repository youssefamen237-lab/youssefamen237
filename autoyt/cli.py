\
from __future__ import annotations

import argparse
from pathlib import Path

from autoyt.pipeline.analyst import run_analyst
from autoyt.pipeline.config import ConfigManager
from autoyt.pipeline.runner import run_bootstrap, run_daily
from autoyt.utils.logging_utils import get_logger, setup_logging

log = get_logger("autoyt.cli")


def _repo_root() -> Path:
    # repo root = parent of this file's package directory
    return Path(__file__).resolve().parents[1]


def cmd_bootstrap(args: argparse.Namespace) -> None:
    repo = _repo_root()
    run_bootstrap(repo, shorts=args.shorts, longs=args.longs, publish_now=args.publish_now)


def cmd_daily(args: argparse.Namespace) -> None:
    repo = _repo_root()
    run_daily(repo, publish_now=args.publish_now)


def cmd_analyst(args: argparse.Namespace) -> None:
    repo = _repo_root()
    cfgm = ConfigManager(repo)
    bundle = cfgm.load()
    new_state = run_analyst(repo, bundle.base, bundle.state, upload_profile_readonly=1, analytics_profile=3)
    cfgm.save_state(new_state)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="autoyt", description="YouTube autopilot pipeline (GitHub Actions).")
    p.add_argument("--log-level", default="INFO", help="Logging level (INFO, DEBUG, WARNING).")

    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bootstrap", help="First real publish run (1 Short + 1 Long by default).")
    b.add_argument("--shorts", type=int, default=1)
    b.add_argument("--longs", type=int, default=1)
    b.add_argument("--publish-now", action="store_true", help="Publish immediately (no scheduling).")
    b.set_defaults(func=cmd_bootstrap)

    d = sub.add_parser("daily", help="Daily pipeline (generate + schedule).")
    d.add_argument("--publish-now", action="store_true", help="Publish immediately (for emergency).")
    d.set_defaults(func=cmd_daily)

    a = sub.add_parser("analyst", help="Run analyst only (update state).")
    a.set_defaults(func=cmd_analyst)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.log_level)
    args.func(args)


if __name__ == "__main__":
    main()
