import argparse
import sys

from ytquiz.config import Config
from ytquiz.pipeline import run_pipeline


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cfg = Config.from_env()
    if args.dry_run:
        cfg = cfg.with_overrides(dry_run=True)

    run_pipeline(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
