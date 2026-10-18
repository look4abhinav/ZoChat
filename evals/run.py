"""CLI entry point for running evals (gated on real keys)."""

from __future__ import annotations

import argparse
import os
import sys

if "ZOCHAT_RUN_EVALS" not in os.environ:
    os.environ["ZOCHAT_RUN_EVALS"] = "1"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="zochat-eval")
    parser.add_argument(
        "suite", choices=["classifier", "support"], nargs="?", default="classifier"
    )
    args = parser.parse_args(argv)
    print(
        f"Eval suite '{args.suite}' is a skeleton; implement case loading in evals/tasks.py"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
