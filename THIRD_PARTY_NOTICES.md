# Third-party notices

The HubICG Python runtime has no third-party runtime dependencies in v0.1.0.

| Component | Purpose | License / terms | Treatment |
|---|---|---|---|
| Python | Runtime and tests | PSF License | External prerequisite |
| SQLite | Optional local role index through Python `sqlite3` | Public domain | Supplied by the Python/platform build; not vendored |
| setuptools | Build backend | MIT | Build dependency only |
| pytest | Tests | MIT | Development dependency only |
| actions/checkout | CI checkout | MIT | GitHub Action by reference |
| actions/setup-python | CI setup | MIT | GitHub Action by reference |
| actions/dependency-review-action | Dependency review | MIT | GitHub Action by reference |
| github/codeql-action | Code scanning | MIT | GitHub Action by reference |
| actions/upload-artifact | Release candidate artifacts | MIT | GitHub Action by reference |

Dependencies are not relicensed as AGPL. Preserve upstream licenses and
attribution, replace incompatible components, or obtain separate permission
before distribution. Review versions and referenced Actions before each release.

## Station source integration (#146)

The selected engine, GUI, contract and test sources originate from HubICG's
AGPL-3.0-only code. No upstream binaries, packages or private configuration are
vendored. Runtime integration uses external platform tools as subprocesses:

| Component | Use | License / terms | Distribution |
|---|---|---|---|
| Windows PowerShell / WinForms | Windows engine and GUI | Windows component terms | Platform prerequisite |
| bash | Linux engine and launcher | GPL-3.0-or-later (3.2: GPL-2.0-or-later) | External prerequisite |
| awk, sed, core utilities | Shell JSON parsing, hashing and files | Platform implementation licenses (GNU/BSD) | External prerequisites |
| Git | Clone and Git identity | GPL-2.0-only | External installation |
| GitHub CLI | Official authentication and access | MIT | External installation |
| curl / OpenSSL | TLS probes and official downloads | curl license / platform OpenSSL license | External prerequisites |
| winget, apt, dnf | Platform package installation | Respective platform terms / GPL | External package managers |
| zenity | Linux native dialogs | LGPL-2.1-or-later | Optional prerequisite |
| kdialog, qdbus | KDE native dialogs and progress | KDE/Qt distribution licenses | Optional prerequisites |
| xdg-utils, GIO | Desktop launch and shortcuts | MIT / LGPL-2.1-or-later | Optional platform prerequisites |
| Claude Code / Claude Desktop | Official tools and login | Anthropic proprietary terms | Downloaded only on explicit application; not bundled |
| Homebrew | Experimental macOS shell path | BSD-2-Clause | External prerequisite; not installed by tests |

Python's standard library handles the public agent export and Linux interface;
there is no added third-party Python runtime dependency. Tests use local fake
executables, never real authentication or downloads. No desktop, CLI or service
licenses are granted by HubICG's own license.
