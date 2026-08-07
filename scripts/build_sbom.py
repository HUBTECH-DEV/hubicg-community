#!/usr/bin/env python3
"""Create the minimal SPDX 2.3 tag-value SBOM for the dependency-free runtime."""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, default=Path("dist/hubicg-0.1.0.spdx"))
args = parser.parse_args()
revision = os.environ.get("GITHUB_SHA", "local-release-candidate")
epoch = os.environ.get("SOURCE_DATE_EPOCH")
created_value = dt.datetime.fromtimestamp(int(epoch), dt.timezone.utc) if epoch else dt.datetime.now(dt.timezone.utc)
created = created_value.replace(microsecond=0).isoformat().replace("+00:00", "Z")
content = f"""SPDXVersion: SPDX-2.3
DataLicense: CC0-1.0
SPDXID: SPDXRef-DOCUMENT
DocumentName: hubicg-0.1.0
DocumentNamespace: https://github.com/HUBTECH-DEV/hubicg-community/sbom/{revision}
Creator: Organization: HUBTECH CONSULTORIA E DESENVOLVIMENTO LTDA
Created: {created}

PackageName: hubicg
SPDXID: SPDXRef-Package-hubicg
PackageVersion: 0.1.0
PackageDownloadLocation: NOASSERTION
FilesAnalyzed: false
PackageLicenseConcluded: AGPL-3.0-only
PackageLicenseDeclared: AGPL-3.0-only
PackageCopyrightText: Copyright 2026 Paulo Cesar Benjamin Junior

Relationship: SPDXRef-DOCUMENT DESCRIBES SPDXRef-Package-hubicg
"""
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(content, encoding="utf-8")
print(f"sbom={args.output}")
