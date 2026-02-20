from core.orchestrator import Orchestrator
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous YouTube AI System")
    parser.add_argument(
        "--mode",
        choices=["autonomous", "bootstrap", "short", "long", "analytics", "recovery"],
        default="autonomous",
    )
    args = parser.parse_args()
    Orchestrator().run(args.mode)


if __name__ == "__main__":
    main()
