"""
main.py
=======
CLI entry point for the MindCraft Psychology automation pipeline.

Usage
-----
    # Run daily Short batch (4 Shorts by default)
    python main.py --mode short

    # Run Short batch with custom count and dry-run (no upload)
    python main.py --mode short --count 2 --dry-run

    # Run weekly compilation
    python main.py --mode weekly

    # Run compilation with unlisted privacy for testing
    python main.py --mode weekly --privacy unlisted --dry-run

    # Validate environment only (no pipeline run)
    python main.py --mode validate
"""

import sys

import click

from config.api_keys import validate_all
from config.settings import DAILY_SHORTS_COUNT, COMPILATION_MAX_CLIPS
from utils.logger import get_logger

logger = get_logger(__name__)


@click.command()
@click.option(
    "--mode",
    type=click.Choice(["short", "weekly", "validate"], case_sensitive=False),
    required=True,
    help=(
        "short    → run daily Short batch\n"
        "weekly   → run weekly compilation\n"
        "validate → check env vars only"
    ),
)
@click.option(
    "--count",
    default=DAILY_SHORTS_COUNT,
    show_default=True,
    help="Number of Shorts to generate (--mode short only).",
)
@click.option(
    "--max-clips",
    default=COMPILATION_MAX_CLIPS,
    show_default=True,
    help="Max Short clips to include in compilation (--mode weekly only).",
)
@click.option(
    "--privacy",
    type=click.Choice(["public", "unlisted", "private"], case_sensitive=False),
    default="public",
    show_default=True,
    help="YouTube privacy status for uploaded videos.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Skip YouTube upload; render and log locally only.",
)
def main(
    mode:      str,
    count:     int,
    max_clips: int,
    privacy:   str,
    dry_run:   bool,
) -> None:
    """MindCraft Psychology — YouTube automation pipeline."""

    if dry_run:
        logger.info("DRY RUN mode active — uploads will be skipped.")

    # ── validate ─────────────────────────────────────────────────────────────
    if mode == "validate":
        try:
            validate_all()
            click.echo("✅  All environment variables are present.")
        except EnvironmentError as exc:
            click.echo(f"❌  Validation failed:\n{exc}", err=True)
            sys.exit(1)
        return

    # ── short ────────────────────────────────────────────────────────────────
    if mode == "short":
        from pipelines.run_short import run_daily_batch

        results = run_daily_batch(
            count=count,
            dry_run=dry_run,
            privacy=privacy,
        )
        successes = sum(1 for r in results if r.success)
        failures  = len(results) - successes

        click.echo(
            f"\n{'='*50}\n"
            f"Short batch complete: {successes}/{len(results)} succeeded"
            f"{'  [DRY RUN]' if dry_run else ''}\n"
            f"{'='*50}"
        )

        if failures:
            for r in results:
                if not r.success:
                    click.echo(f"  ✗ {r.error}", err=True)

        sys.exit(0 if successes > 0 else 1)

    # ── weekly ───────────────────────────────────────────────────────────────
    if mode == "weekly":
        from pipelines.run_weekly import run_weekly_compilation

        result = run_weekly_compilation(
            dry_run=dry_run,
            privacy=privacy,
            max_clips=max_clips,
        )

        if result.success:
            click.echo(
                f"\n{'='*50}\n"
                f"Compilation uploaded successfully"
                f"{'  [DRY RUN]' if dry_run else ''}\n"
                f"  URL      : {result.youtube_url or 'n/a (dry run)'}\n"
                f"  Clips    : {result.clip_count}\n"
                f"  Duration : {result.duration_secs:.1f}s\n"
                f"{'='*50}"
            )
            sys.exit(0)
        else:
            click.echo(f"\n❌  Compilation failed: {result.error}", err=True)
            sys.exit(1)


if __name__ == "__main__":
    main()
