# Windows and Linux station

The canonical engines are `hubicg-station.ps1` (Windows PowerShell 5.1) and
`hubicg-station.sh` (bash). See [the event contract](../../docs/architecture/station-installer-engine.md).
The [interfaces](ui/README.md) conduct these engines without duplicating installation logic.

From a Community checkout, generate the agent artifact first (Python 3.11+):

```sh
python scripts/build_station_agents.py
```

The export verifies the public library's manifest, renders its roles through
the public Claude adapter and includes each composed foundation. Files go to
`.hubicg/exports/station-agents/`; no private configuration or library is needed.
Existing differing exports are preserved: choose a fresh `--output` directory
and supply it through `-AgentsSource` / `--agents-source`. The installer checks
each body's SHA-256 marker before writing agents. A missing export becomes
`action_required`, never an assertion that agents were installed. Hash markers
detect edits; they do not authenticate an untrusted external artifact.
The export receipt pins the public library manifest. The default path is checked
against the selected clone, including after a pull. A stale or missing receipt
requires action: preserve the old export directory under another name, then
generate a fresh export at the default path. An explicit external source uses
its own provenance and does not assert freshness against the selected clone.

If the installer's selected clone directory differs from this checkout,
pass this export's absolute path with `-AgentsSource` / `--agents-source`, or
generate the export in the selected clone when prompted. These options belong
to the engine; the GUI uses the selected clone's default export directory.

Windows: double-click `ui/windows/Instalar-HubICG-Estacao.cmd`.
Linux: run `sh installers/station/ui/linux/hubicg-station-ui.sh`; Python 3,
zenity or kdialog with qdbus, or an interactive terminal is required.
Use `--criar-atalho` to create a menu/desktop entry from the Linux launcher.

Both engines support check and plan modes, official authentication, bounded
CLI status probes, preserving edited files and repeatable installation.
Applying the engine may install Git, GitHub CLI and Claude tools, configure
Git identity and write the chosen clone/Claude directories. Read the contract
before applying. Linux reports Claude Desktop as unsupported. macOS shell
support is experimental; this change includes no macOS GUI or full Mac acceptance.

Run `make station-test` for isolated engine/interface tests. They use fake
executables and temporary HOME/configuration paths, without real login,
downloads or workstation installation. Real VM/login acceptance is separate
in the runbooks, and remains required before claiming full real installation.
