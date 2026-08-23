#!/usr/bin/env python3
"""Emit a canonical SHA-256 digest for the generated public demo artifact."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    artifact = args.artifact.read_bytes()
    if not artifact.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SystemExit("Expected a PNG artifact")
    args.output.write_text(hashlib.sha256(artifact).hexdigest() + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
