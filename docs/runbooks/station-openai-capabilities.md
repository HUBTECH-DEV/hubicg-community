# Optional OpenAI station capabilities

Issue #150 adds generic Windows capabilities to the existing public engine.
They do not set organizational policy, instructions, account requirements or
workspace/domain restrictions. Linux/macOS recognize the same IDs and report
`unsupported` when selected. This is an implementation boundary, not a claim
about vendor availability. Real installation/login and visual acceptance remain
separate from the isolated automated tests.

## Selection and modes

```powershell
# Read-only capability checks (logs may be written).
.\installers\station\hubicg-station.ps1 -Check -Only codex-cli,codex-cli-auth,chatgpt-desktop,chatgpt-desktop-auth
# Preview: no download, installation, login, app launch or state acknowledgement.
.\installers\station\hubicg-station.ps1 -WhatIf -Only codex-cli,chatgpt-desktop
# Apply explicitly selected installations under the intended Windows user.
.\installers\station\hubicg-station.ps1 -Only codex-cli,chatgpt-desktop
```

The existing default selection is unchanged. All four new IDs appear at the end
of `run_start.data.steps` and emit `skipped` unless explicitly selected. Dependencies
are not automatically selected. In apply mode failed/pending installation blocks
its selected authentication step. Selecting authentication alone checks the
existing application; an acknowledgement cannot install Desktop.

Check/plan never authenticate or open apps. Apply also leaves OpenAI login to an
explicit user action: the engine emits the known action and rerunning checks
completion. Interfaces must use their own known action catalog; event `command`
and `url` fields are descriptive data, never executable authority.

## Installation and detection

Sources checked on 2026-10-23:

- [Codex CLI](https://learn.chatgpt.com/docs/cli) and [Windows deployment](https://learn.chatgpt.com/docs/enterprise/windows-deployment)
  document the standalone installer at `https://chatgpt.com/codex/install.ps1`.
  Apply downloads it with TLS verification, runs it in a child PowerShell,
  checks its exit code and then verifies `codex --version`. Installer output
  is not copied into public events/logs. No npm dependency is added.
- [Installer environment variables](https://learn.chatgpt.com/docs/config-file/environment-variables)
  document `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin`, `CODEX_INSTALL_DIR`,
  `CODEX_HOME` and `CODEX_NON_INTERACTIVE`. An existing PATH command has priority;
  otherwise the engine checks `codex.exe` in the effective installer directory.
  It does not overwrite an existing unresponsive/unversioned CLI. The child
  inherits overrides; `CODEX_NON_INTERACTIVE=1` is scoped to installation and
  restored afterwards. The official installer manages User PATH. No machine
  PATH or global configuration is changed by the wrapper. Fresh terminal
  resolution remains part of real acceptance.
- [ChatGPT for Windows](https://learn.chatgpt.com/docs/app/windows) gives
  `winget install --id 9PLM9XGG6VKS -s msstore`.
  The wrapper adds `--silent`, `--accept-package-agreements`,
  `--accept-source-agreements` and `--disable-interactivity`, documented by
  [Microsoft's install command](https://learn.microsoft.com/en-us/windows/package-manager/winget/install),
  for scripted application. It does not pass unsupported vendor installer flags.
  [Windows deployment](https://learn.chatgpt.com/docs/enterprise/windows-deployment)
  explicitly identifies the current ChatGPT MSIX as `OpenAI.Codex`. The historical
  package name does not identify a different legacy application. Detection uses
  `Get-AppxPackage -Name OpenAI.Codex` for the current user only, before and after
  installation; a successful installer exit alone is insufficient.
  A query error is inconclusive and returns `failed` with `data.detection=unknown`,
  including in check/plan. It never becomes `missing` or triggers an install.
  The engine relies on the official Store installation trust chain; it does not
  invent a publisher string, executable, AUMID, window title or URI scheme. It
  does not provision an all-users package or bypass Store/TLS restrictions.

Missing winget emits the existing `package-manager-missing/external` action for
the new `chatgpt-desktop` step, pointing to App Installer in the Microsoft Store.
Consumers must explicitly allow this new step/action pairing. Store/network/
permission failure or absent per-user registration is `failed`; the engine does
not substitute an unrelated EXE or claim offline success.

## Authentication and evidence

[Authentication](https://learn.chatgpt.com/docs/auth) and the
[CLI reference](https://learn.chatgpt.com/docs/cli/reference) document `codex login`
and `codex login status`. The status probe closes stdin and has a 30-second
deadline. Exit 0 confirms generic local CLI authentication only. Other exits,
missing command or timeout leave authentication unconfirmed. No auth cache,
token, account email or workspace is read by the wrapper; status output is
discarded. The engine never copies credentials between apps.

| Step | Action ID / kind | Response / completion |
| --- | --- | --- |
| `codex-cli-auth` | `codex-login` / `run_in_terminal` | Run known `codex login` explicitly; rerun engine to probe official status. No answer field. |
| `chatgpt-desktop-auth` | `chatgpt-desktop-login-confirm` / `confirm` | `chatgpt.loginConfirmed`: boolean, required=true, human declaration label, no default. |

For Desktop the user opens ChatGPT from Start, selects Continue on the signed-out
screen and completes the official browser flow. The engine does not launch the
app or infer session state from CLI authentication. Answer via the existing
answers-file protocol and rerun:

```json
{"schema":"hubicg.station.answers/1","answers":{"chatgpt.loginConfirmed":true}}
```

Absent keeps an unresolved request pending. Explicit false overrides any earlier
timestamp: check/plan describe pending status without writes; apply removes the
previous ChatGPT acknowledgement and asks again. Claude state is preserved.
The acknowledgement persists only after
per-user app detection, under the exclusive `chatgptDesktopLoginConfirmedAt`
field in the existing state file. A repeat run reports the earlier declaration;
it does not claim the session is still valid. `data.evidence=user_declared` and
`identityVerified=false` distinguish it from automatic verification.
Claude's `desktop.loginConfirmed` / `desktopLoginConfirmedAt` remain independent.
Neither acknowledgement establishes account, domain, instructions or workspace.
Persistence failure returns `failed`, never `configured`. Existing states without
the new field remain valid, and unrelated writes preserve it.

## Validation and downstream export

Run the canonical isolated station suites with
`HUBICG_STATION_ENGINE_TESTS=1`, including `tests/test_station_installer.py` and
the existing public export, simulator and interface suites. Tests supply fake
Codex/winget/curl and temporary user/config paths; none installs or authenticates
real apps. POSIX tests must use a frozen source snapshot if editing continues.

After integration and successful main CI, the coordinator must use the complete
integrated source SHA, not this worktree's base or a PR/draft SHA. From a clean
checkout of that SHA, run canonical `scripts/build_manifest.py --check`, then
`scripts/build_station_agents.py --output <fresh-export-directory>`.
The export uses only the packaged public library, verifies it and writes the
real `.hubicg-station-export.json` receipt. Count the actual agents; do not label
an export by an expected count or fabricate a receipt to match a consumer pin.

Source packaging must include at least:

- `installers/station/` (both engines, `json-read.awk`, UI catalog/launchers);
- `docs/architecture/station-installer-engine.md`,
  `docs/schemas/station-event.schema.json`, this capability document;
- `scripts/build_station_agents.py`, `MANIFEST.sha256`;
- the canonical runtime renderer/library inputs under `src/hubicg/`, public
  schemas, `pyproject.toml` and the actual verified agent export/receipt;
- `LICENSE`, `LICENSES/`, `LICENSING.md`, `NOTICE`, `THIRD_PARTY_NOTICES.md`.

Use `git archive <integrated-full-sha>` to preserve the source snapshot, plus
the fresh canonical export. The consuming packaging tool must record the actual
source SHA, inventory and SHA-256 of every delivered file and archive, together
with its real descriptor/receipt. Verify those inventories before handing off.
Preserve historical ZIPs/pins. Export alone does not create a release or establish
a final runtime pin. The coordinator owns final packaging/pinning/publication.
