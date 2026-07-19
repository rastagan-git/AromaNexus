"""Compatibility wrapper for :mod:`aromanexus.cli`."""

from aromanexus.cli import build_parser, main

__all__ = ["build_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
