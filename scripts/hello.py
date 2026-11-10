#!/usr/bin/env python3
"""Thin entry point mandated by the issue (AC1). No logic: it calls src.hello."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.hello import main  # noqa: E402

if __name__ == "__main__":
    main()
