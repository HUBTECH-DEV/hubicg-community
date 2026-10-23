#!/usr/bin/env python3
"""Motor simulado do instalador da estacao HubICG (contrato hubicg.station.event/1).

Serve para testar as interfaces da #83 sem instalar nada. Emite eventos validos
pelo esquema docs/schemas/station-event.schema.json, com os mesmos codigos de
saida do contrato (docs/architecture/station-installer-engine.md), e guarda o
estado entre execucoes para que a segunda passada em modo aplicacao termine em
``already``, como o motor real.

Aceita as duas grafias de opcao (``-Json`` do PowerShell e ``--json`` do bash),
porque a mesma fixture conduz a interface do Windows e a do Linux.

Variaveis de ambiente (so desta fixture; nao fazem parte do contrato):

- ``HUBICG_STATION_SIM_STATE``: arquivo de estado (padrao: no diretorio temporario).
- ``HUBICG_STATION_SIM_SCENARIO``: ``default``, ``fail``, ``tls``, ``repo-access``,
  ``terminal-login``, ``code-timeout``, ``invalid-email`` ou ``unsupported-os``.
- ``HUBICG_STATION_SIM_OS``: ``windows``, ``linux`` ou ``macos`` (padrao: o sistema atual).
- ``HUBICG_STATION_SIM_DELAY_MS``: pausa entre eventos, para ver o progresso (padrao: 0).
- ``HUBICG_STATION_SIM_CODE_WAIT``: segundos de espera no ``browser_code`` (padrao: 1).
- ``HUBICG_STATION_SIM_BROWSER_OPENED``: ``1`` declara que a ferramenta ja abriu o navegador
  (``browserOpenedByTool``), para os testes de tela nao abrirem o navegador de verdade.
"""

from __future__ import annotations

import json
import os
import platform
import re
import secrets
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "hubicg.station.event/1"
ENGINE_VERSION = "0.0.0-simulado"

STEPS = (
    "environment",
    "git",
    "git-identity",
    "gh",
    "gh-auth",
    "repo",
    "claude-cli",
    "claude-cli-auth",
    "claude-desktop",
    "claude-desktop-auth",
    "agents",
)
DEPENDS = {
    "git-identity": ("git",),
    "gh-auth": ("gh",),
    "repo": ("git", "gh-auth"),
    "claude-cli-auth": ("claude-cli",),
    "claude-desktop-auth": ("claude-desktop",),
    "agents": ("repo",),
}
OK = {"checked", "already", "installed", "updated", "configured", "unsupported", "skipped"}
STOPPED = {"failed", "action_required", "blocked"}
KNOWN_ANSWERS = {
    "git.name",
    "git.email",
    "git.useSystemCertStore",
    "claude.addToPath",
    "desktop.loginConfirmed",
}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

FLAGS = {
    "check": ("-check", "--check"),
    "whatif": ("-whatif", "--dry-run"),
    "json": ("-json", "--json"),
    "noninteractive": ("-noninteractive", "--non-interactive"),
    "skipnetwork": ("-skipnetwork", "--skip-network"),
    "contract": ("-contractversion", "--contract-version"),
    "usewincert": ("-usewindowscertstore",),
    "addtopath": ("--add-to-path",),
    "confirmdesktop": ("-confirmdesktoplogin", "--confirm-desktop-login"),
}
VALUED = {
    "only": ("-only", "--only"),
    "answers": ("-answersfile", "--answers-file"),
    "repodir": ("-repodir", "--repo-dir"),
    "configdir": ("-configdir", "--config-dir"),
    "logfile": ("-logfile", "--log-file"),
    "gitname": ("-gitname", "--git-name"),
    "gitemail": ("-gitemail", "--git-email"),
}


class UsageError(Exception):
    pass


def parse_args(argv: list[str]) -> dict[str, Any]:
    options: dict[str, Any] = {name: False for name in FLAGS}
    options.update({name: None for name in VALUED})
    index = 0
    while index < len(argv):
        token = argv[index]
        lowered = token.lower()
        for name, spellings in FLAGS.items():
            if lowered in spellings:
                options[name] = True
                break
        else:
            for name, spellings in VALUED.items():
                if lowered in spellings:
                    if index + 1 >= len(argv):
                        raise UsageError(f"a opção {token} exige um valor")
                    index += 1
                    options[name] = argv[index]
                    break
            else:
                raise UsageError(f"opção desconhecida: {token}")
        index += 1
    return options


class Engine:
    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        self.json = bool(options["json"])
        self.mode = "check" if options["check"] else "plan" if options["whatif"] else "apply"
        self.os = os.environ.get("HUBICG_STATION_SIM_OS") or {
            "Windows": "windows",
            "Darwin": "macos",
        }.get(platform.system(), "linux")
        self.scenario = os.environ.get("HUBICG_STATION_SIM_SCENARIO", "default")
        self.delay = int(os.environ.get("HUBICG_STATION_SIM_DELAY_MS", "0")) / 1000
        self.code_wait = float(os.environ.get("HUBICG_STATION_SIM_CODE_WAIT", "1"))
        self.state_path = Path(
            os.environ.get("HUBICG_STATION_SIM_STATE")
            or Path(tempfile.gettempdir()) / "hubicg-station-sim-state.json"
        )
        self.state = self._load_state()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = f"{stamp}-{secrets.token_hex(2)}"
        self.seq = 0
        self.results: dict[str, str] = {}
        home = Path.home()
        self.repo_dir = options["repodir"] or str(home / "github" / "hubicg-community")
        self.config_dir = options["configdir"] or os.environ.get("CLAUDE_CONFIG_DIR") or str(
            home / ".claude"
        )
        self.log_path = Path(
            options["logfile"]
            or Path(tempfile.gettempdir()) / "hubicg-station-sim-logs" / f"station-{self.run_id}.jsonl"
        )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_handle = self.log_path.open("w", encoding="utf-8", newline="\n")
        self.answers = self._load_answers()

    # -- estado -------------------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"done": {}, "seen": {}}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def done(self, key: str) -> bool:
        return bool(self.state["done"].get(key))

    def mark(self, key: str, value: Any = True) -> None:
        self.state["done"][key] = value

    def seen(self, key: str) -> bool:
        return bool(self.state["seen"].get(key))

    def see(self, key: str) -> None:
        self.state["seen"][key] = True

    def _load_answers(self) -> dict[str, Any]:
        answers: dict[str, Any] = {}
        path = self.options["answers"]
        if path:
            document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if document.get("schema") != "hubicg.station.answers/1":
                raise UsageError("arquivo de respostas com schema desconhecido")
            answers.update(document.get("answers") or {})
        if self.options["gitname"]:
            answers["git.name"] = self.options["gitname"]
        if self.options["gitemail"]:
            answers["git.email"] = self.options["gitemail"]
        if self.options["confirmdesktop"]:
            answers["desktop.loginConfirmed"] = True
        if self.options["usewincert"]:
            answers["git.useSystemCertStore"] = True
        if self.options["addtopath"]:
            answers["claude.addToPath"] = True
        return answers

    # -- saida --------------------------------------------------------------

    def emit(self, type_: str, step: str = "", status: str = "", message: str = "", **data: Any) -> None:
        self.seq += 1
        event = {
            "schema": SCHEMA,
            "runId": self.run_id,
            "seq": self.seq,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": type_,
            "step": step,
            "status": status,
            "message": message,
            "data": data,
        }
        logged = dict(event, data={k: v for k, v in data.items() if k != "code"})
        if data.get("code"):
            logged["message"] = message.replace(str(data["code"]), "[redacted]")
        self.log_handle.write(json.dumps(logged, ensure_ascii=False) + "\n")
        self.log_handle.flush()
        if self.json:
            sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
        else:
            label = f"[{step}] " if step else ""
            sys.stdout.write(f"{label}{status + ': ' if status else ''}{message}\n")
        sys.stdout.flush()
        if self.delay:
            time.sleep(self.delay)

    def progress(self, step: str, message: str) -> None:
        for percent in (0, 35, 70, 100):
            self.emit("progress", step, "", message, percent=percent)

    def action(self, step: str, message: str, **data: Any) -> None:
        data.setdefault("blocking", False)
        self.emit("action_required", step, "action_required", message, **data)

    # -- execucao -----------------------------------------------------------

    def run(self) -> int:
        if self.scenario == "unsupported-os":
            sys.stderr.write("sistema sem suporte (cenario simulado)\n")
            return 4
        selected = set(STEPS)
        if self.options["only"]:
            requested = {item.strip() for item in self.options["only"].split(",") if item.strip()}
            unknown = requested - set(STEPS)
            if unknown:
                sys.stderr.write(f"etapa desconhecida: {', '.join(sorted(unknown))}\n")
                return 2
            selected = requested | {"environment"}
        unknown_answers = sorted(set(self.answers) - KNOWN_ANSWERS)

        self.emit(
            "run_start",
            message="Instalador da estação HubICG (motor simulado).",
            engine=ENGINE_VERSION,
            contract=1,
            mode=self.mode,
            os=self.os,
            interactive=not self.options["noninteractive"],
            steps=list(STEPS),
            repoDir=self.repo_dir,
            configDir=self.config_dir,
            logFile=str(self.log_path),
        )
        total = len(STEPS)
        for index, step in enumerate(STEPS, start=1):
            self.emit("step_start", step, "", f"Etapa {step}", index=index, total=total)
            if step == "environment" and unknown_answers:
                for key in unknown_answers:
                    self.emit("log", step, "warn", f"Resposta desconhecida ignorada: {key}")
            if step not in selected:
                status, message, data = "skipped", "Fora da seleção.", {}
            else:
                status, message, data = getattr(self, "step_" + step.replace("-", "_"))()
            self.results[step] = status
            self.emit("step_end", step, status, message, **data)

        exit_code = self.exit_code()
        self.emit(
            "run_end",
            status="",
            message=self.final_message(exit_code),
            exitCode=exit_code,
            steps=dict(self.results),
        )
        if self.mode == "apply":
            self._save_state()
        self.log_handle.close()
        return exit_code

    def exit_code(self) -> int:
        statuses = set(self.results.values())
        if "failed" in statuses:
            return 1
        if statuses & {"action_required", "blocked"}:
            return 3
        if statuses & {"missing", "would_install", "would_configure", "would_update"}:
            return 5
        return 0

    @staticmethod
    def final_message(code: int) -> str:
        return {
            0: "Tudo pronto.",
            1: "Houve falhas. Veja as etapas e o log.",
            3: "Há pendências que dependem de você.",
            5: "Há o que instalar ou configurar.",
        }.get(code, "")

    def blocked_by(self, step: str) -> list[str]:
        return [dep for dep in DEPENDS.get(step, ()) if self.results.get(dep) in STOPPED]

    def simple(self, step: str, key: str, kind: str, label: str, command: str) -> tuple[str, str, dict]:
        """Etapa de instalacao simples: verifica, simula ou instala."""
        if self.done(key):
            return "already", f"{label} já estava instalado.", {"version": "1.0.0"}
        if self.mode == "check":
            return "missing", f"{label} não está instalado.", {}
        if self.mode == "plan":
            return f"would_{kind}", f"{label} seria instalado.", {"command": command}
        self.progress(step, f"Baixando {label}")
        self.mark(key)
        return "installed", f"{label} instalado.", {"version": "1.0.0"}

    def pending(self, step: str, done: bool, label: str) -> tuple[str, str, dict] | None:
        """Para etapas de configuracao: resolve os modos verificacao e simulacao."""
        if done:
            return "already", f"{label} já estava configurado.", {}
        if self.mode == "check":
            return "missing", f"{label} ainda não está configurado.", {}
        if self.mode == "plan":
            return "would_configure", f"{label} seria configurado.", {}
        blocked = self.blocked_by(step)
        if blocked:
            return "blocked", "Aguardando etapas anteriores.", {"blockedBy": blocked}
        return None

    def step_environment(self) -> tuple[str, str, dict]:
        tls = "inspected" if self.scenario == "tls" else "direct"
        hosts = ("github.com", "api.github.com", "claude.ai", "api.anthropic.com", "downloads.claude.ai")
        if self.options["skipnetwork"]:
            network: Any = "skipped"
            tls = "skipped"
        else:
            issuer = "Netskope Root CA" if tls == "inspected" else "DigiCert Global G2"
            network = {
                host: {"verdict": tls, "issuer": issuer, "trusted": tls == "direct"} for host in hosts
            }
        if tls == "inspected":
            self.emit(
                "log",
                "environment",
                "warn",
                "Inspeção TLS corporativa detectada (Netskope). O Git precisa usar o repositório de "
                "certificados do sistema (http.sslBackend=schannel) e o Node precisa de "
                "NODE_EXTRA_CA_CERTS. A verificação TLS não será desligada.",
            )
        windows = self.os == "windows"
        data = {
            "os": self.os,
            "osVersion": "10.0.26300" if windows else "24.04",
            "arch": "AMD64" if windows else "x86_64",
            "shell": "powershell" if windows else "bash",
            "shellVersion": "5.1.26100.1" if windows else "5.2.21",
            "admin": False,
            "sudo": None if windows else "password",
            "packageManager": "winget" if windows else "apt",
            "diskFreeGB": 120.4,
            "proxy": {},
            "tools": {
                "git": "2.47.1" if self.done("git") else None,
                "gh": "2.80.0" if self.done("gh") else None,
                "claude": "2.1.300" if self.done("claude-cli") else None,
            },
            "network": network,
            "tls": tls,
        }
        return "checked", "Ambiente verificado.", data

    def step_git(self) -> tuple[str, str, dict]:
        status, message, data = self.simple("git", "git", "install", "Git", "winget install Git.Git")
        if self.mode != "apply" or self.scenario != "tls" or self.os != "windows":
            return status, message, data
        decision = self.answers.get("git.useSystemCertStore")
        if self.done("git-cert") or decision is False:
            return status, message, data
        if decision is True:
            self.mark("git-cert")
            return "configured", "Git configurado para usar os certificados do Windows.", data
        self.action(
            "git",
            "A rede usa inspeção TLS. Quer que o Git use os certificados do Windows "
            "(http.sslBackend=schannel)?",
            id="git-system-cert-store",
            kind="confirm",
            answers=[
                {
                    "key": "git.useSystemCertStore",
                    "type": "boolean",
                    "label": "Usar os certificados do Windows no Git",
                    "required": True,
                    "default": True,
                }
            ],
        )
        return "action_required", "Aguardando sua decisão sobre os certificados.", data

    def step_git_identity(self) -> tuple[str, str, dict]:
        early = self.pending("git-identity", self.done("git-identity"), "A identidade do Git")
        if early:
            return early
        name = str(self.answers.get("git.name") or "").strip()
        email = str(self.answers.get("git.email") or "").strip()
        if self.scenario == "invalid-email" and not self.seen("invalid-email"):
            self.see("invalid-email")
            email = email or "invalido"
        message = "Informe o nome e o e-mail que vão assinar os commits."
        if name and email and EMAIL.match(email):
            self.mark("git-identity", {"name": name, "email": email})
            return "configured", f"Identidade do Git configurada para {name}.", {}
        if email and not EMAIL.match(email):
            message = f"O e-mail “{email}” não é válido. " + message
        self.action(
            "git-identity",
            message,
            id="git-identity",
            kind="input",
            answers=[
                {"key": "git.name", "type": "string", "label": "Nome", "required": True},
                {"key": "git.email", "type": "email", "label": "E-mail", "required": True},
            ],
        )
        return "action_required", "Falta a identidade do Git.", {}

    def step_gh(self) -> tuple[str, str, dict]:
        return self.simple("gh", "gh", "install", "GitHub CLI", "winget install GitHub.cli")

    def step_gh_auth(self) -> tuple[str, str, dict]:
        ready = self.done("gh-auth") and (self.scenario != "repo-access" or self.done("repo-access"))
        early = self.pending("gh-auth", ready, "A sessão do GitHub")
        if early:
            return early
        if not self.done("gh-auth"):
            if self.scenario == "terminal-login":
                if not self.seen("gh-login"):
                    self.see("gh-login")
                    self.action(
                        "gh-auth",
                        "Entre no GitHub pelo terminal com o comando oficial.",
                        id="gh-login",
                        kind="run_in_terminal",
                        command="gh auth login --web --git-protocol https",
                    )
                    return "action_required", "Falta entrar no GitHub.", {}
            else:
                self.action(
                    "gh-auth",
                    "Abra https://github.com/login/device e digite o código ABCD-1234.",
                    id="gh-login",
                    kind="browser_code",
                    blocking=True,
                    url="https://github.com/login/device",
                    code="ABCD-1234",
                    timeoutSeconds=900,
                    browserOpenedByTool=os.environ.get("HUBICG_STATION_SIM_BROWSER_OPENED") == "1",
                )
                time.sleep(self.code_wait)
                result = {"code-timeout": "timeout"}.get(self.scenario, "completed")
                if self.scenario == "code-timeout" and self.seen("code-timeout"):
                    result = "completed"
                self.see("code-timeout")
                self.emit(
                    "action_resolved",
                    "gh-auth",
                    result,
                    "Login no GitHub concluído." if result == "completed" else "O código expirou.",
                    id="gh-login",
                )
                if result != "completed":
                    return "action_required", "O login no GitHub não foi concluído.", {}
            self.mark("gh-auth")
        if self.scenario == "repo-access" and not self.done("repo-access"):
            if self.seen("repo-access"):
                self.mark("repo-access")
            else:
                self.see("repo-access")
                self.action(
                    "gh-auth",
                    "Sua conta ainda não tem acesso a HUBTECH-DEV/hubicg-community. Peça acesso a um "
                    "owner da organização e depois verifique de novo.",
                    id="repo-access",
                    kind="external",
                    url="https://github.com/HUBTECH-DEV/hubicg-community",
                )
                return "action_required", "Falta acesso ao repositório.", {}
        return "configured", "Sessão do GitHub ativa e configurada para o Git.", {}

    def step_repo(self) -> tuple[str, str, dict]:
        if self.done("repo"):
            return "already", "O clone já estava atualizado.", {"path": self.repo_dir}
        if self.mode == "check":
            return "missing", "O repositório ainda não foi clonado.", {}
        if self.mode == "plan":
            return "would_install", "O repositório seria clonado.", {"command": "git clone ..."}
        blocked = self.blocked_by("repo")
        if blocked:
            return "blocked", "Aguardando etapas anteriores.", {"blockedBy": blocked}
        self.progress("repo", "Clonando HUBTECH-DEV/hubicg-community")
        self.mark("repo")
        return "installed", f"Repositório clonado em {self.repo_dir}.", {"path": self.repo_dir}

    def step_claude_cli(self) -> tuple[str, str, dict]:
        if self.scenario == "fail" and self.mode == "apply" and not self.done("claude-cli"):
            self.emit("log", "claude-cli", "error", "O download do instalador oficial falhou.")
            return (
                "failed",
                "Não foi possível instalar o Claude Code CLI.",
                {"output": "curl: (35) schannel: connection reset (saída simulada)"},
            )
        status, message, data = self.simple(
            "claude-cli", "claude-cli", "install", "Claude Code CLI", "irm https://claude.ai/install.ps1 | iex"
        )
        if self.mode != "apply" or self.os == "windows" or self.done("claude-path"):
            return status, message, data
        decision = self.answers.get("claude.addToPath")
        if decision is not None:
            self.mark("claude-path")
            if decision is True:
                return "configured", "~/.local/bin incluído no PATH do perfil do shell.", data
            return status, message, data
        self.action(
            "claude-cli",
            "O comando claude fica em ~/.local/bin, que não está no PATH. Incluir no perfil do shell?",
            id="claude-path",
            kind="confirm",
            answers=[
                {
                    "key": "claude.addToPath",
                    "type": "boolean",
                    "label": "Incluir ~/.local/bin no PATH",
                    "required": True,
                    "default": True,
                }
            ],
        )
        return "action_required", "Aguardando sua decisão sobre o PATH.", data

    def step_claude_cli_auth(self) -> tuple[str, str, dict]:
        early = self.pending("claude-cli-auth", self.done("claude-cli-auth"), "A sessão do Claude Code")
        if early:
            return early
        if self.seen("claude-login"):
            self.mark("claude-cli-auth")
            return "configured", "Sessão do Claude Code ativa.", {}
        self.see("claude-login")
        self.action(
            "claude-cli-auth",
            "Entre no Claude Code pelo terminal. O comando abre o navegador e pode pedir para colar um "
            "código de volta no terminal.",
            id="claude-login",
            kind="run_in_terminal",
            command="claude auth login",
        )
        return "action_required", "Falta entrar no Claude Code.", {}

    def step_claude_desktop(self) -> tuple[str, str, dict]:
        if self.os == "linux":
            return "unsupported", "O Claude Desktop não existe para Linux.", {}
        return self.simple(
            "claude-desktop", "claude-desktop", "install", "Claude Desktop", "winget install Anthropic.Claude"
        )

    def step_claude_desktop_auth(self) -> tuple[str, str, dict]:
        if self.os == "linux":
            return "unsupported", "O Claude Desktop não existe para Linux.", {}
        early = self.pending("claude-desktop-auth", self.done("claude-desktop-auth"), "O login no Claude Desktop")
        if early:
            return early
        if self.answers.get("desktop.loginConfirmed") is True:
            self.mark("claude-desktop-auth")
            return "configured", "Login no Claude Desktop confirmado.", {}
        self.action(
            "claude-desktop-auth",
            "Abra o Claude Desktop, entre com a sua conta e confirme aqui quando terminar.",
            id="desktop-login-confirm",
            kind="confirm",
            answers=[
                {
                    "key": "desktop.loginConfirmed",
                    "type": "boolean",
                    "label": "Já entrei no Claude Desktop",
                    "required": True,
                }
            ],
        )
        return "action_required", "Falta confirmar o login no Claude Desktop.", {}

    def step_agents(self) -> tuple[str, str, dict]:
        target = str(Path(self.config_dir) / "agents")
        counts = {"installed": 0, "updated": 0, "already": 0, "removed": 0, "conflict": 0}
        if self.done("agents"):
            counts["already"] = 65
            return "already", "Os 65 agentes já estavam instalados.", {
                "target": target, "source": "simulado", "total": 65, "counts": counts, "conflicts": []
            }
        if self.mode == "check":
            return "missing", "Os agentes HubICG ainda não foram instalados.", {}
        if self.mode == "plan":
            return "would_install", "65 agentes seriam instalados.", {}
        blocked = self.blocked_by("agents")
        if blocked:
            return "blocked", "Aguardando o clone do repositório.", {"blockedBy": blocked}
        counts["installed"] = 65
        self.mark("agents")
        return "installed", "65 agentes HubICG instalados.", {
            "target": target, "source": "simulado", "total": 65, "counts": counts, "conflicts": []
        }


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        options = parse_args(argv)
    except UsageError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    if options["contract"]:
        sys.stdout.write(SCHEMA + "\n")
        return 0
    try:
        return Engine(options).run()
    except UsageError as error:
        sys.stderr.write(f"{error}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
