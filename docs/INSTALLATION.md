# Installation

HubICG v0.1.0 requires Python 3.11 or 3.12 and has no third-party runtime
dependencies.

## Install a verified wheel

Download the wheel and `SHA256SUMS` from the approved release, verify the
checksum, then install it in an isolated environment:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install hubicg-0.1.0-py3-none-any.whl
hubicg --root . validate
```

On Windows PowerShell, activate with:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install .\hubicg-0.1.0-py3-none-any.whl
hubicg --root . validate
```

`pipx install hubicg-0.1.0-py3-none-any.whl` is also supported for a
user-scoped CLI installation.

The Community release is not published to PyPI in v0.1.0. Do not install an
unverified package that merely uses the same name.

## Initialize local roles

```sh
hubicg --root . roles verify
hubicg --root . roles db init
hubicg --root . roles db import --source project
hubicg --root . roles select "arquitetura idioma:pt" --count 2
hubicg --root . roles db status
```

The database, backups, exports and change evidence remain under `.hubicg/` and
are excluded from Git by default.
