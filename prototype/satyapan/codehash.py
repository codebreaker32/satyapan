"""One hash of the engine code and the data it decides with, so preflight can tell a stale server from a fresh one.

The rulebook hash alone misses a server still running an older extract.py or pipeline.py: any change to Python and not
to rulebook.yaml passes "server meta: rulebook sha matches local". Campaign memory is left out on purpose, because
the server rewrites that file as analysts propose and approve entries.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
DATA = PACKAGE.parent / "data"


def code_sha256() -> str:
    h = hashlib.sha256()
    files = sorted(PACKAGE.glob("*.py")) + sorted((DATA / "rules").glob("*")) + [DATA / "fixtures" / "scenarios.json"]
    for f in files:
        if f.is_file():
            h.update(f.relative_to(PACKAGE.parent).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()
