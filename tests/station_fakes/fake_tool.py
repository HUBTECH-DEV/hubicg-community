#!/usr/bin/env python3
"""Ferramentas falsas para testar os motores do instalador da estação.

Os motores chamam git, gh, winget, apt-get, dnf, sudo, curl, claude e id pelo
PATH. Nos testes, o PATH aponta para lançadores que chamam este script com o
nome da ferramenta. O estado da "máquina" mora num JSON (``FAKE_STATE``) e cada
chamada é registrada em ``calls.jsonl`` ao lado dele, para os testes provarem o
que o motor executou e, principalmente, o que ele **não** executou.

Uma ferramenta está "instalada" quando o lançador dela existe em ``FAKE_BIN``.
Os gerenciadores de pacotes falsos instalam criando o lançador; nada sai da
pasta temporária do teste.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

# Native Git/Claude emit UTF-8. Python's redirected Windows default can be
# cp1252, which cannot represent the Unicode fixtures used by the tests.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

STATE = Path(os.environ["FAKE_STATE"])
BIN = Path(os.environ["FAKE_BIN"])
CALLS = STATE.with_name("calls.jsonl")
WINDOWS = os.name == "nt"

PACKAGES = {
    "Git.Git": "git", "GitHub.cli": "gh",
    "git": "git", "gh": "gh", "curl": "curl", "ca-certificates": None,
}


def load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8"))


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def make_launcher(name: str) -> None:
    """Create the PATH entry that makes ``name`` look installed."""
    python = sys.executable
    script = Path(__file__).resolve()
    if WINDOWS:
        (BIN / f"{name}.cmd").write_text(
            f'@"{python}" "{script}" {name} %*\r\n@exit /b %ERRORLEVEL%\r\n', encoding="ascii"
        )
    else:
        path = BIN / name
        path.write_text(f'#!/bin/sh\nexec "{python}" "{script}" {name} "$@"\n', encoding="ascii")
        path.chmod(0o755)


def out(text: str) -> None:
    sys.stdout.write(text + "\n")


def err(text: str) -> None:
    sys.stderr.write(text + "\n")


def fake_git(args: list[str], state: dict) -> int:
    config = state.setdefault("git_config", {})
    if args == ["--version"]:
        out("git version 2.47.1")
        return 0
    if args and args[0] == "-C":
        repo = Path(args[1])
        sub = args[2:]
        if sub[:3] == ["remote", "get-url", "origin"]:
            out((repo / ".git" / "fake-remote").read_text(encoding="utf-8").strip())
            return 0
        if sub[:2] == ["status", "--porcelain"]:
            if state.get("repo_dirty"):
                out(" M arquivo.txt")
            return 0
        if sub[:2] == ["rev-parse", "HEAD"]:
            out(state.get("local_head", "a" * 40))
            return 0
        if sub[:1] == ["fetch"]:
            return 0
        if sub[:2] == ["pull", "--ff-only"]:
            state["local_head"] = state.get("remote_head", state.get("local_head", "a" * 40))
            save(state)
            return 0
        return 0
    if args[:1] == ["clone"]:
        url, target = args[1], Path(args[2])
        (target / ".git").mkdir(parents=True)
        (target / ".git" / "fake-remote").write_text(url, encoding="utf-8")
        shutil.copytree(os.environ["FAKE_AGENTS_SOURCE"], target / ".hubicg" / "exports" / "station-agents")
        state["local_head"] = state.get("remote_head", "a" * 40)
        save(state)
        return 0
    if args[:1] == ["config"]:
        rest = [a for a in args[1:] if a not in ("--global",)]
        if rest[:1] == ["--get"]:
            values = config.get(rest[1])
            if not values:
                return 1
            out(values[-1])
            return 0
        if rest[:1] == ["--get-all"]:
            values = config.get(rest[1])
            if not values:
                return 1
            for value in values:
                out(value)
            return 0
        if len(rest) == 2:
            if state.get("git_config_readonly"):
                err("error: could not lock config file")
                return 255
            config[rest[0]] = [rest[1]]
            save(state)
            return 0
    return 0


def fake_gh(args: list[str], state: dict) -> int:
    if args == ["--version"]:
        out("gh version 2.62.0 (2024-11-14)")
        return 0
    if args[:2] == ["auth", "status"]:
        if state.get("gh_auth"):
            err("github.com\n  Logged in to github.com account fake (keyring)\n  Token: gho_************************************")
            return 0
        err("You are not logged into any GitHub hosts.")
        return 1
    if args[:2] == ["auth", "login"]:
        # Without a terminal, the real gh prints the code and the URL and does
        # not wait for Enter; the login completes when the browser approves.
        err("! First copy your one-time code: ABCD-1234")
        err("Open this URL to continue in your web browser: https://github.com/login/device")
        if state.get("gh_login_succeeds", True):
            state["gh_auth"] = True
            save(state)
            err("✓ Authentication complete.")
            return 0
        return 1
    if args[:2] == ["auth", "setup-git"]:
        state.setdefault("git_config", {})["credential.https://github.com.helper"] = [
            "", "!/usr/bin/gh auth git-credential"
        ]
        save(state)
        return 0
    if args[:2] == ["repo", "view"]:
        return 0 if state.get("gh_access", True) else 1
    return 0


def fake_package_manager(args: list[str], state: dict) -> int:
    if args == ["--version"]:
        out("v1.9.2" if WINDOWS else "apt 2.7.14 (amd64)")
        return 0
    if "install" not in args:
        return 0
    names = [a for a in args if not a.startswith("-") and a not in ("install",)]
    if "--id" in args:
        names = [args[args.index("--id") + 1]]
    for name in names:
        tool = PACKAGES.get(name, name)
        if tool:
            make_launcher(tool)
    return 0


def fake_sudo(args: list[str], state: dict) -> int:
    if args[:2] == ["-n", "true"]:
        return 0 if state.get("sudo_passwordless", True) else 1
    if args == ["--version"]:
        out("Sudo version 1.9.15")
        return 0
    os.execvp(args[0], args)
    return 127


def fake_curl(args: list[str], state: dict) -> int:
    if args == ["--version"]:
        out("curl 8.5.0")
        return 0
    if "-o" not in args:
        return 0
    target = Path(args[args.index("-o") + 1])
    url = args[-1]
    python = sys.executable
    script = Path(__file__).resolve()
    if url.endswith("install.sh"):
        target.write_text(f'#!/bin/sh\n"{python}" "{script}" __install claude\n', encoding="ascii")
    elif url.endswith("install.ps1"):
        target.write_text(f'& "{python}" "{script}" __install claude\r\n', encoding="ascii")
    else:
        target.write_bytes(b"fake-download")
    return 0


def fake_claude(args: list[str], state: dict) -> int:
    if args == ["--version"]:
        out("2.1.300 (Claude Code)")
        return 0
    if args[:2] == ["auth", "status"]:
        if state.get("claude_auth_delay"):
            time.sleep(state["claude_auth_delay"])
        if "claude_auth_reply" in state:
            out(json.dumps({"loggedIn": state["claude_auth_reply"]}))
            return state.get("claude_auth_exit", 0)
        if state.get("claude_without_auth_command"):
            err("error: unknown command 'auth'")
            return 1
        logged = bool(state.get("claude_auth"))
        out(json.dumps({
            "loggedIn": logged,
            "authMethod": "claude.ai" if logged else "none",
            "email": "pessoa@exemplo.com.br",
            "orgName": "Organizacao Secreta",
            "configDirectory": state.get("claude_config_dir", ""),
        }))
        sys.stdout.flush()
        if state.get("claude_auth_delay_after_output"):
            state["auth_output_ready"] = True
            save(state)
            time.sleep(state["claude_auth_delay_after_output"])
        return 0 if logged else 1
    return 0


def fake_id(args: list[str], state: dict) -> int:
    out(str(state.get("uid", 1000)))
    return 0


def fake_dpkg(args: list[str], state: dict) -> int:
    out("amd64")
    return 0


def fake_openssl(args: list[str], state: dict) -> int:
    if args[:1] == ["s_client"]:
        out("fake-certificate")
    elif args[:1] == ["x509"]:
        out("issuer=CN=Untrusted Private CA")
    else:
        out("OpenSSL 3.2.0")
    return 0


def fake_brew(args: list[str], state: dict) -> int:
    if args == ["--version"]:
        out("Homebrew 4.5.0")
        return 0
    if "--cask" in args and "claude" in args:
        (Path(os.environ["HOME"]) / "Applications" / "Claude.app").mkdir(parents=True, exist_ok=True)
        return 0
    return fake_package_manager(args, state)


def fake_uname(args: list[str], state: dict) -> int:
    out(state.get("mac_arch", "x86_64") if args == ["-m"] else "Darwin")
    return 0


def fake_sw_vers(args: list[str], state: dict) -> int:
    out(state.get("mac_version", "15.8"))
    return 0


TOOLS = {
    "git": fake_git, "gh": fake_gh, "winget": fake_package_manager,
    "apt-get": fake_package_manager, "dnf": fake_package_manager, "sudo": fake_sudo,
    "curl": fake_curl, "claude": fake_claude, "id": fake_id, "dpkg": fake_dpkg,
    "openssl": fake_openssl,
    "brew": fake_brew, "uname": fake_uname, "sw_vers": fake_sw_vers,
}


def main() -> int:
    name, args = sys.argv[1], sys.argv[2:]
    if name == "__install":
        make_launcher(args[0])
        return 0
    with CALLS.open("a", encoding="utf-8") as log:
        log.write(json.dumps({"tool": name, "args": args}) + "\n")
    return TOOLS[name](args, load())


if __name__ == "__main__":
    sys.exit(main())
