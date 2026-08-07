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
user = event["pull_request"]["user"]
author = user["login"]
account_id = str(user["id"])
account_type = str(user.get("type", ""))

# Machine-generated dependency updates do not represent a human contribution
# capable of accepting a CLA. Trust only GitHub's official Dependabot identity;
# the pull request still requires all technical checks and maintainer review.
trusted_automation = {
    ("dependabot[bot]", "49699333", "Bot"),
}
automation = (author, account_id, account_type) in trusted_automation

maintainers = (root / "MAINTAINERS.md").read_text(encoding="utf-8")
registry = (root / "CLA_REGISTRY.md").read_text(encoding="utf-8")
trusted = bool(re.search(rf"(?<![\w-])@{re.escape(author)}(?![\w-])", maintainers))
registered = bool(re.search(rf"\|\s*@{re.escape(author)}\s*\|\s*{re.escape(account_id)}\s*\|", registry))

if not (trusted or registered or automation):
    raise SystemExit(
        f"CLA required for @{author} (GitHub account ID {account_id}). "
        "Record a reviewed acceptance entry in CLA_REGISTRY.md."
    )
source = "maintainer" if trusted else "registry" if registered else "trusted-automation"
print(f"cla=valid actor={author} source={source}")
