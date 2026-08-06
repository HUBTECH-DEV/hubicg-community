#!/usr/bin/env python3
"""Enforce that a pull-request author is trusted or has a public CLA record."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
event_path = Path(os.environ["GITHUB_EVENT_PATH"])
event = json.loads(event_path.read_text(encoding="utf-8"))
author = event["pull_request"]["user"]["login"]
account_id = str(event["pull_request"]["user"]["id"])

maintainers = (root / "MAINTAINERS.md").read_text(encoding="utf-8")
registry = (root / "CLA_REGISTRY.md").read_text(encoding="utf-8")
trusted = bool(re.search(rf"(?<![\w-])@{re.escape(author)}(?![\w-])", maintainers))
registered = bool(re.search(rf"\|\s*@{re.escape(author)}\s*\|\s*{re.escape(account_id)}\s*\|", registry))

if not (trusted or registered):
    raise SystemExit(
        f"CLA required for @{author} (GitHub account ID {account_id}). "
        "Record a reviewed acceptance entry in CLA_REGISTRY.md."
    )
print(f"cla=valid actor={author} source={'maintainer' if trusted else 'registry'}")
