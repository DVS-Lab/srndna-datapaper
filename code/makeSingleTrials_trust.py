#!/usr/bin/env python3
"""Compatibility entry point for Trust LSS EV generation."""

from __future__ import annotations

import sys

from makeSingleTrials import main


if __name__ == "__main__":
    raise SystemExit(main(["trust", *sys.argv[1:]]))
