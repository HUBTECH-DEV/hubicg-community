#!/usr/bin/env python3
"""Assistente grafico (L1) do instalador da estacao HubICG no Linux.

Conduz o motor ``installers/station/hubicg-station.sh`` pelo contrato ``hubicg.station.event/1``
(docs/architecture/station-installer-engine.md). Usa ``zenity``; no KDE, ``kdialog``; sem ambiente
grafico, o modo terminal. O assistente so mostra o que o motor emite e devolve as respostas por arquivo e
nova execucao: nao instala nada por conta propria e nunca pede senha ou token.

Usa so a biblioteca padrao do Python 3, que ja vem nos desktops Linux suportados. Os textos pt-BR vem de
``../station-ui-texts.json``, o mesmo arquivo da interface do Windows.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

HERE = Path(__file__).resolve().parent
TEXTS_PATH = HERE.parent / "station-ui-texts.json"
DEFAULT_ENGINE = HERE.parent.parent / "hubicg-station.sh"
EVENT_SCHEMA = "hubicg.station.event/1"
ANSWERS_SCHEMA = "hubicg.station.answers/1"
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TERMINALS = (
    ("x-terminal-emulator", ["-e"]),
    ("ptyxis", ["--"]),
    ("kgx", ["--"]),
    ("gnome-terminal", ["--"]),
    ("konsole", ["-e"]),
    ("xfce4-terminal", ["-x"]),
    ("mate-terminal", ["-x"]),
    ("tilix", ["-e"]),
    ("xterm", ["-e"]),
)
OK_STEP = {"checked", "already", "unsupported", "skipped"}


# --- nucleo: o mesmo papel de StationUi.Core.ps1 -----------------------------------------------------


class Texts:
    def __init__(self, path: Path = TEXTS_PATH) -> None:
        self.data = json.loads(path.read_text(encoding="utf-8"))

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def step(self, step: str) -> str:
        return self.data["steps"].get(step, step)

    def status(self, status: str) -> dict[str, Any]:
        """Grupo e rotulo de um status; desconhecido conta como falha (contrato, secao 9)."""
        known = self.data["statuses"].get(status)
        if known:
            return {"label": known["label"], "group": known["group"], "known": True}
        return {"label": self.data["unknownStatus"].format(status), "group": "failed", "known": False}

    def exit_message(self, code: int | None) -> str:
        message = self.data["exitCodes"].get(str(code))
        return message or self.data["exitCodes"]["unknown"].format(code)

    def action_guide(self, action: dict[str, Any]) -> dict[str, str]:
        by_id = self.data["actions"].get(action.get("id", ""))
        by_kind = self.data["kinds"].get(action.get("kind", "")) or self.data["kinds"]["external"]
        chosen = by_id or by_kind
        return {"title": chosen["title"], "guide": chosen["guide"]}


def parse_event(line: str) -> dict[str, Any] | None:
    """Devolve o evento, ou None para linha vazia, JSON invalido ou outro schema."""
    line = line.strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if not isinstance(event, dict) or event.get("schema") != EVENT_SCHEMA or not event.get("type"):
        return None
    if not isinstance(event.get("data"), dict):
        event["data"] = {}
    return event


class RunState:
    """Estado de uma execucao do motor, reconstruido evento a evento."""

    def __init__(self) -> None:
        self.run_id: str | None = None
        self.mode: str | None = None
        self.os: str | None = None
        self.steps: list[str] = []
        self.status: dict[str, str] = {}
        self.messages: dict[str, str] = {}
        self.step_data: dict[str, dict[str, Any]] = {}
        self.current: str | None = None
        self.index = 0
        self.total = 0
        self.percent: float | None = None
        self.actions: list[dict[str, Any]] = []
        self.blocking: dict[str, Any] | None = None
        self.resolved: list[dict[str, Any]] = []
        self.logs: list[dict[str, Any]] = []
        self.environment: dict[str, Any] | None = None
        self.repo_dir: str | None = None
        self.config_dir: str | None = None
        self.log_file: str | None = None
        self.exit_code: int | None = None
        self.ended = False
        self.last_seq = 0
        self.gaps = 0
        self.ignored = 0
        self.recovered: list[str] = []

    def apply(self, event: dict[str, Any] | None) -> str | None:
        if event is None:
            self.ignored += 1
            return None
        seq = int(event.get("seq") or 0)
        if self.last_seq and seq > self.last_seq + 1:
            self.gaps += seq - self.last_seq - 1
        self.last_seq = max(self.last_seq, seq)
        kind = event["type"]
        step = event.get("step") or ""
        status = event.get("status") or ""
        message = event.get("message") or ""
        data = event["data"]
        if kind == "run_start":
            self.run_id = event.get("runId")
            self.mode = data.get("mode")
            self.os = data.get("os")
            self.repo_dir = data.get("repoDir")
            self.config_dir = data.get("configDir")
            self.log_file = data.get("logFile")
            self.steps = [str(item) for item in data.get("steps") or []]
            self.total = len(self.steps)
        elif kind == "step_start":
            if step not in self.steps:
                self.steps.append(step)
            self.current = step
            self.index = int(data.get("index") or self.steps.index(step) + 1)
            self.total = int(data.get("total") or self.total)
            self.percent = None
        elif kind == "progress":
            self.percent = data.get("percent")
            self.messages[step] = message
        elif kind == "log":
            self.logs.append({"level": status, "step": step, "message": message,
                              "command": data.get("command"), "output": data.get("output")})
        elif kind == "action_required":
            action = {
                "step": step, "message": message, "id": str(data.get("id") or ""),
                "kind": str(data.get("kind") or ""), "blocking": bool(data.get("blocking")),
                "answers": list(data.get("answers") or []), "command": data.get("command"),
                "url": data.get("url"), "code": data.get("code"),
                "timeoutSeconds": data.get("timeoutSeconds"),
                "browserOpenedByTool": bool(data.get("browserOpenedByTool")),
            }
            if action["blocking"]:
                self.blocking = action
            else:
                self.actions.append(action)
        elif kind == "action_resolved":
            self.resolved.append({"id": data.get("id"), "status": status, "message": message})
            self.blocking = None
        elif kind == "step_end":
            if step not in self.steps:
                self.steps.append(step)
            self.status[step] = status
            self.messages[step] = message
            self.step_data[step] = data
            if step == "environment":
                self.environment = data
            self.percent = None
            if self.blocking and self.blocking["step"] == step:
                self.blocking = None
        elif kind == "run_end":
            final_steps = data.get("steps")
            if isinstance(final_steps, dict):
                for final_step, final_status in final_steps.items():
                    if not isinstance(final_status, str):
                        continue
                    if final_step not in self.steps:
                        self.steps.append(final_step)
                    if self.status.get(final_step) != final_status:
                        self.status[final_step] = final_status
                        self.messages[final_step] = "Status recuperado do resumo do motor; detalhes indisponíveis."
                        self.recovered.append(final_step)
            self.exit_code = int(data.get("exitCode", 1))
            self.ended = True
            self.current = None
        else:
            self.ignored += 1
            return None
        return kind

    def complete(self, process_code: int) -> int:
        """Fecha o estado com o codigo do processo. Sem run_end, a execucao foi interrompida (130)."""
        if not self.ended:
            self.exit_code = process_code if process_code in (2, 4) else 130
            self.ended = True
        self.blocking = None
        if self.exit_code == 0 and any(not Texts().status(status)["known"] for status in self.status.values()):
            self.exit_code = 1
        return int(self.exit_code)

    def overall_percent(self) -> int:
        if self.total <= 0:
            return 0
        partial = 0.0
        if self.current and self.current not in self.status and self.percent is not None:
            partial = float(self.percent) / 100
        return max(0, min(100, int((len(self.status) + partial) / self.total * 100)))


class Session:
    """Resultado acumulado das execucoes encadeadas de uma mesma instalacao."""

    def __init__(self) -> None:
        self.status: dict[str, str] = {}
        self.messages: dict[str, str] = {}

    def merge(self, texts: Texts, state: RunState) -> RunState:
        """O que uma execucao anterior fez nao vira "Ja estava" no resumo final da instalacao."""
        for step in state.steps:
            if step not in state.status:
                continue
            new = state.status[step]
            previous = self.status.get(step)
            if previous and texts.status(previous)["group"] == "done" and new in ("already", "skipped"):
                continue
            self.status[step] = new
            self.messages[step] = state.messages.get(step, "")
        merged = RunState()
        merged.__dict__.update(state.__dict__)
        merged.status = dict(self.status)
        merged.messages = dict(self.messages)
        return merged


def summary(texts: Texts, state: RunState) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = {"failed": [], "action": [], "pending": [], "done": [], "ok": []}
    for step in state.steps:
        if step not in state.status:
            continue
        info = texts.status(state.status[step])
        groups[info["group"]].append({
            "step": step, "label": texts.step(step), "status": info["label"],
            "message": state.messages.get(step, ""),
        })
    return groups


def environment_rows(texts: Texts, data: dict[str, Any] | None) -> list[dict[str, str]]:
    """Linhas do relatorio de ambiente: item, valor, severidade (ok, info, warn, error) e explicacao."""
    if not data:
        return []
    t = texts["environment"]
    rows: list[dict[str, str]] = []

    def add(item: str, value: Any, severity: str = "ok", explain: str = "") -> None:
        rows.append({"item": item, "value": str(value), "severity": severity, "explain": explain})

    os_name = t["osNames"].get(str(data.get("os")), data.get("os"))
    add(t["os"], f"{os_name} {data.get('osVersion') or ''} ({data.get('arch') or ''})".strip())
    if data.get("shell"):
        add(t["shell"], f"{data.get('shell')} {data.get('shellVersion') or ''}".strip())
    if data.get("admin") is not None:
        add(t["admin"], t["yes"] if data["admin"] else t["no"], "info")
    sudo = data.get("sudo")
    if sudo:
        label = t["sudoValues"].get(sudo, sudo)
        add(t["sudo"], label, "warn" if sudo == "absent" else "ok",
            t["explain"]["sudoAbsent"] if sudo == "absent" else "")
    if data.get("packageManager"):
        add(t["packageManager"], data["packageManager"])
    else:
        add(t["packageManager"], t["none"], "warn", t["explain"]["noPackageManager"])
    disk = data.get("diskFreeGB")
    if disk is None:
        add(t["diskFreeGB"], t["notMeasured"], "info")
    else:
        value = f"{float(disk):.1f} GB".replace(".", ",")
        add(t["diskFreeGB"], value, "warn" if float(disk) < 5 else "ok",
            t["explain"]["lowDisk"] if float(disk) < 5 else "")
    proxy = data.get("proxy") or {}
    if isinstance(proxy, dict) and proxy:
        add(t["proxy"], "; ".join(f"{k}={v}" for k, v in proxy.items()), "info", t["explain"]["proxy"])
    else:
        add(t["proxy"], t["none"])
    tls = data.get("tls")
    if tls:
        severity = {"direct": "ok", "inspected": "warn", "suspected": "warn", "unreachable": "error",
                    "skipped": "info"}.get(tls, "warn")
        add(t["tls"], t["verdicts"].get(tls, tls), severity, t["explain"]["tls"].get(tls, ""))
    network = data.get("network")
    if isinstance(network, dict):
        for host, entry in network.items():
            verdict = str((entry or {}).get("verdict") or "")
            severity = "ok" if verdict == "direct" else "error" if verdict == "unreachable" else "warn"
            add(f"{t['network']} {host}", t["verdicts"].get(verdict, verdict), severity,
                t["explain"]["tls"].get(verdict, ""))
    for tool, version in (data.get("tools") or {}).items():
        if version:
            add(f"{t['tools']}: {tool}", version)
        else:
            add(f"{t['tools']}: {tool}", t["absentTool"], "info")
    return rows


def engine_arguments(mode: str = "apply", only: Iterable[str] = (), repo_dir: str | None = None,
                     answers_file: str | None = None) -> list[str]:
    """Opcoes do motor no estilo bash. A interface sempre usa --json e --non-interactive."""
    arguments: list[str] = []
    if mode == "check":
        arguments.append("--check")
    elif mode == "plan":
        arguments.append("--dry-run")
    arguments += ["--json", "--non-interactive"]
    selected = [step for step in only if step]
    if selected:
        arguments += ["--only", ",".join(selected)]
    if repo_dir:
        arguments += ["--repo-dir", repo_dir]
    if answers_file:
        arguments += ["--answers-file", answers_file]
    return arguments


def engine_command(engine: Path, arguments: list[str]) -> list[str]:
    """Programa e argumentos do motor: .sh roda no bash; .py (motor simulado), no Python atual."""
    if engine.suffix == ".sh":
        return ["bash", str(engine), *arguments]
    if engine.suffix == ".py":
        return [sys.executable, str(engine), *arguments]
    return [str(engine), *arguments]


def validate_answer(kind: str, value: Any, required: bool) -> bool:
    """Validacao local, so para orientar a pessoa; quem decide e o motor."""
    if kind == "boolean":
        return isinstance(value, bool) or (not required and value is None)
    text = "" if value is None else str(value).strip()
    if not text:
        return not required
    if kind == "email":
        return EMAIL.match(text) is not None
    return True


def write_answers_file(answers: dict[str, Any], directory: str | None = None) -> str:
    """Grava o arquivo de respostas (UTF-8, so leitura do dono) e devolve o caminho."""
    clean = {key: value.strip() if isinstance(value, str) else value for key, value in answers.items()}
    path = Path(directory or tempfile.gettempdir()) / f"hubicg-station-answers-{uuid.uuid4().hex}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"schema": ANSWERS_SCHEMA, "answers": clean}, handle, ensure_ascii=False, indent=2)
    return str(path)


def default_selection(check: RunState) -> list[str]:
    """Todas as etapas, menos environment (sempre roda) e as que nao se aplicam ao sistema."""
    return [step for step in check.steps if step != "environment" and check.status.get(step) != "unsupported"]


# --- execucao do motor -----------------------------------------------------------------------------


class EngineRun:
    """Roda o motor e entrega cada evento a um callback, na ordem. cancel() encerra o motor e os filhos."""

    def __init__(self, engine: Path, arguments: list[str]) -> None:
        self.engine = engine
        self.command = engine_command(engine, arguments)
        self.state = RunState()
        self.stderr = ""
        self.process: subprocess.Popen[str] | None = None
        self.cancelled = False
        self.cancel_lock = threading.Lock()
        self.kill_timer: threading.Timer | None = None

    def run(self, on_event: Callable[[RunState, dict[str, Any], str], None]) -> RunState:
        if self.cancelled:
            self.state.complete(130)
            return self.state
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        self.process = subprocess.Popen(
            self.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", env=env,
            start_new_session=(os.name == "posix"),
        )
        if self.cancelled:
            self.cancel()
        errors: list[str] = []
        reader = threading.Thread(target=lambda: errors.append(self.process.stderr.read()), daemon=True)
        reader.start()
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                event = parse_event(line)
                kind = self.state.apply(event)
                if kind and event is not None:
                    on_event(self.state, event, kind)
            code = self.process.wait()
        except BaseException:
            self.cancel()
            raise
        finally:
            if self.process.poll() is None:
                self.cancel()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(self.process.pid, signal.SIGKILL)
                    else:
                        self.process.kill()
                    self.process.wait()
            if self.kill_timer:
                self.kill_timer.join(timeout=3)
            reader.join(timeout=5)
            self.process.stdout.close()
            if self.process.stderr:
                self.process.stderr.close()
            self.stderr = "".join(errors)
        self.state.complete(code)
        return self.state

    def cancel(self) -> None:
        self.cancelled = True
        process = self.process
        if not process:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            elif process.poll() is None:
                process.terminate()
        except (ProcessLookupError, PermissionError):
            pass
        # Independente do leitor de stdout: um filho pode ignorar TERM e manter o pipe aberto.
        with self.cancel_lock:
            if self.kill_timer is None:
                self.kill_timer = threading.Timer(2, self.force_cancel)
                self.kill_timer.daemon = True
                self.kill_timer.start()

    def force_cancel(self) -> None:
        process = self.process
        if not process:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
        except (ProcessLookupError, PermissionError):
            pass


# --- utilidades do sistema -------------------------------------------------------------------------


def which(name: str) -> str | None:
    return shutil.which(name)


def open_url(url: str | None) -> None:
    if url and url.startswith("https://") and which("xdg-open"):
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def copy_to_clipboard(text: str) -> bool:
    for command in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if which(command[0]):
            try:
                subprocess.run(command, input=text, text=True, timeout=5, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except (subprocess.SubprocessError, OSError):
                continue
    return False


def terminal_command(inner: list[str]) -> list[str] | None:
    """Comando para abrir um emulador de terminal rodando ``inner``, ou None se nao houver nenhum."""
    for name, flag in TERMINALS:
        path = which(name)
        if path:
            return [path, *flag, *inner]
    return None


def fresh_env() -> dict[str, str]:
    """O motor pode ter instalado o claude em ~/.local/bin; este processo ainda nao tem isso no PATH."""
    env = dict(os.environ)
    local_bin = str(Path.home() / ".local" / "bin")
    if local_bin not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = local_bin + os.pathsep + env.get("PATH", "")
    return env


def open_terminal_with(command: str) -> bool:
    script = f'{command}\nprintf "\\n%s" "Terminou? Pressione Enter para fechar esta janela."\nread -r _'
    launch = terminal_command(["bash", "-lc", script])
    if not launch:
        return False
    subprocess.Popen(launch, env=fresh_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return True


def system_tools_group_alive(record: dict[str, Any], *, exclude: int | None = None) -> bool:
    """Linux process-group identity; zombies cannot write state or install packages."""
    if Path("/proc/sys/kernel/random/boot_id").read_text().strip() != record["bootId"]:
        return False
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal() or int(entry.name) == exclude:
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(") ", 1)[1].split()
            if fields[0] != "Z" and int(fields[2]) == record["pgid"] and int(fields[3]) == record["sid"]:
                return True
        except FileNotFoundError:
            continue
        except PermissionError:
            # Never release another engine when liveness cannot be established.
            return True
    return False


def claim_system_tools_terminal() -> tuple[dict[str, Any], int]:
    import ctypes
    # Linux adopts orphan descendants here even when sudo/setsid changes their session.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "Não foi possível supervisionar descendentes")
    descriptor = os.pidfd_open(os.getpid())
    os.close(descriptor)
    if not hasattr(signal, "pidfd_send_signal"):
        raise OSError("Sinalização por identidade de processo indisponível")
    previous = os.tcgetpgrp(0)
    if os.getpgrp() != os.getpid():
        os.setpgid(0, 0)
    old = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    try:
        os.tcsetpgrp(0, os.getpgrp())
    finally:
        signal.signal(signal.SIGTTOU, old)
    start = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(") ", 1)[1].split()[19]
    return {"pid": os.getpid(), "start": start, "armed": False, "pgid": os.getpgrp(), "sid": os.getsid(0),
            "bootId": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}, previous


def system_tools_descendants() -> dict[int, str]:
    """Walk kernel child lists, including threads and orphans adopted by the subreaper."""
    found: dict[int, str] = {}
    pending = [os.getpid()]
    seen: set[int] = set()
    while pending:
        parent = pending.pop()
        if parent in seen:
            continue
        seen.add(parent)
        try:
            for task in Path(f"/proc/{parent}/task").iterdir():
                for raw in (task / "children").read_text().split():
                    pid = int(raw)
                    try:
                        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
                    except FileNotFoundError:
                        continue
                    if fields[0] != "Z":
                        found[pid] = fields[19]
                        pending.append(pid)
        except FileNotFoundError:
            continue
    return found


def atomic_helper_record(directory: Path, record: dict[str, Any]) -> None:
    temporary = directory / "started.tmp"
    temporary.write_text(json.dumps(record), encoding="utf-8")
    temporary.replace(directory / "started")


def system_tools_children_complete(child: subprocess.Popen | None) -> bool:
    """Only ECHILD proves completion; /proc discovery can race orphan adoption."""
    if child is not None and child.poll() is None:
        return False
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:  # ECHILD, including all adopted descendants
            return True
        if pid == 0:
            return False


def signal_helper_descendants(signum: int) -> None:
    for pid, start in system_tools_descendants().items():
        descriptor = None
        try:
            descriptor = os.pidfd_open(pid)
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
            if fields[19] == start:
                signal.pidfd_send_signal(descriptor, signum)
        except (ProcessLookupError, FileNotFoundError, PermissionError):
            # A privileged operation we cannot signal remains supervised and blocks the GUI.
            continue
        finally:
            if descriptor is not None:
                os.close(descriptor)


def helper_tools(request: dict[str, Any]) -> list[str]:
    tools = request.get("tools")
    if not isinstance(tools, list) or not tools or any(tool not in ("git", "gh") for tool in tools):
        raise ValueError("Etapas externas não autorizadas")
    return [tool for tool in ("git", "gh") if tool in tools]


def system_tools_child(directory: Path, ready_fd: int) -> int:
    # No installation can begin until the parent has recorded this process group.
    if os.geteuid() == 0 or not (os.isatty(0) and os.isatty(1)):
        return 4
    ready = os.read(ready_fd, 1)
    os.close(ready_fd)
    if ready != b"1":
        return 130
    request = json.loads((directory / "request.json").read_text())
    command = ["bash", str(Path(request["engine"]).resolve()), "--only", ",".join(helper_tools(request)),
               "--repo-dir", str(Path(request["repoDir"]).resolve()),
               "--config-dir", str(directory / "config"), "--log-file", str(directory / "engine.jsonl")]
    os.execvpe(command[0], command, os.environ)
    return 4


def run_system_tools_helper(directory: Path) -> int:
    """Run only Git/GH as the normal user on a real terminal, with isolated state."""
    code = 4
    child: subprocess.Popen | None = None
    handlers: dict[int, Any] = {}
    record: dict[str, Any] | None = None
    previous_group: int | None = None
    ready_write: int | None = None
    if directory.is_symlink() or directory.stat().st_uid != os.geteuid() or directory.stat().st_mode & 0o077:
        return code
    try:
        if os.geteuid() == 0 or not (sys.stdin.isatty() and sys.stdout.isatty()):
            return code
        request_file = directory / "request.json"
        if request_file.is_symlink():
            return code
        request = json.loads(request_file.read_text(encoding="utf-8"))
        if request.get("schema") != "hubicg.station.system-tools/1":
            return code
        helper_tools(request)
        import fcntl
        with (directory / "launch.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if (directory / "result.json").exists():
                return code
            record, previous_group = claim_system_tools_terminal()
            # Publish the group before any child exists; lock excludes stale-launch recovery.
            if (directory / "started").exists():
                return code
            atomic_helper_record(directory, record)
        def interrupt(signum: int, frame: Any) -> None:
            raise KeyboardInterrupt
        for signum in (signal.SIGTERM, signal.SIGHUP):
            handlers[signum] = signal.signal(signum, interrupt)
        ready_read, ready_write = os.pipe()
        try:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                      "--system-tools-child", str(directory), str(ready_read)],
                                     pass_fds=(ready_read,), preexec_fn=os.setpgrp)
        finally:
            os.close(ready_read)
        record["pgid"] = child.pid
        record["armed"] = True
        atomic_helper_record(directory, record)
        old = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        try:
            os.tcsetpgrp(0, child.pid)
        finally:
            signal.signal(signal.SIGTTOU, old)
        os.write(ready_write, b"1")
        os.close(ready_write)
        ready_write = None
        code = child.wait()
        # The original engine may leave adopted setsid descendants. Ctrl+C must reach us.
        old = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        try:
            os.tcsetpgrp(0, os.getpgrp())
        finally:
            signal.signal(signal.SIGTTOU, old)
        while not system_tools_children_complete(child):
            time.sleep(0.1)
        return code
    except KeyboardInterrupt:
        if record is not None and child is not None and record["pgid"] == child.pid:
            # Only the engine's dedicated foreground group is signalled, never the GUI/helper.
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                signal.signal(sig, signal.SIG_IGN)
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal_helper_descendants(sig)
                deadline = time.monotonic() + 3
                while not system_tools_children_complete(child) and time.monotonic() < deadline:
                    time.sleep(0.1)
                if system_tools_children_complete(child):
                    break
            if not system_tools_children_complete(child):
                signal_helper_descendants(signal.SIGKILL)
                while not system_tools_children_complete(child):
                    # Privileged descendants may reject user signals: remain pending, never fake completion.
                    signal_helper_descendants(signal.SIGKILL)
                    time.sleep(0.1)
            if child is not None:
                child.wait()
        code = 130
        return code
    except (OSError, ValueError, KeyError):
        return code
    finally:
        if ready_write is not None:
            os.close(ready_write)
        if previous_group is not None:
            old = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
            try:
                os.tcsetpgrp(0, previous_group)
            except OSError:
                pass
            signal.signal(signal.SIGTTOU, old)
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
        # Keep logs/state for diagnosis; never remove a live helper's directory.
        result = directory / "result.json"
        if not result.exists() and system_tools_children_complete(child):
            with result.open("x", encoding="utf-8") as stream:
                json.dump({"exitCode": code}, stream)


class SystemToolsHelper:
    """One pending external cycle; event command strings are never used here."""

    def __init__(self, engine: Path, repo_dir: Callable[[], str], selection: Callable[[], list[str]] = lambda: ["git", "gh"]) -> None:
        self.engine = engine.resolve()
        self.repo_dir = repo_dir
        self.selection = selection
        self.reason = "A etapa externa ainda está no terminal. Conclua ou cancele com Ctrl+C antes de verificar de novo."
        self.directory: Path | None = None
        self.process: subprocess.Popen | None = None
        self.launched_at = time.monotonic()

    def pending(self) -> bool:
        if self.directory is None:
            return False
        started = self.directory / "started"
        if started.exists():
            try:
                record = json.loads(started.read_text())
                if Path("/proc/sys/kernel/random/boot_id").read_text().strip() != record["bootId"]:
                    (self.directory / "result.json").write_text('{"exitCode":130}', encoding="utf-8")
                    return False
                try:
                    fields = Path(f'/proc/{record["pid"]}/stat').read_text().rsplit(") ", 1)[1].split()
                    if fields[0] != "Z" and fields[19] == record["start"]:
                        return True
                except FileNotFoundError:
                    pass
                if system_tools_group_alive(record):
                    return True
            except (OSError, ValueError, KeyError):
                return True
            if not (self.directory / "result.json").exists() and record.get("armed"):
                self.reason = ("A supervisão externa foi perdida sem comprovar o término de todos os descendentes. "
                               "Nenhum novo motor será iniciado. Preserve os logs; reinicie o Linux para encerrar "
                               "com segurança processos privilegiados não verificáveis antes de tentar novamente.")
                return True
            if not (self.directory / "result.json").exists():
                (self.directory / "result.json").write_text('{"exitCode":130}', encoding="utf-8")
            return False
        if (self.directory / "result.json").exists():
            return False
        if (time.monotonic() - self.launched_at > 60 or
                (self.process is not None and self.process.poll() not in (None, 0))):
            import fcntl
            with (self.directory / "launch.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                if not started.exists():
                    # A late terminal will see the cancelled request under this same lock.
                    (self.directory / "result.json").write_text('{"exitCode":4}', encoding="utf-8")
                    return False
            return True
        return True

    def preview(self) -> str:
        return shlex.join(["bash", str(self.engine), "--only", ",".join(self.authorized_tools())]) + " (logs e estado temporários próprios)"

    def authorized_tools(self) -> list[str]:
        return [tool for tool in ("git", "gh") if tool in self.selection()]

    def launch(self, *, here: bool = False) -> bool:
        if self.pending():
            return True
        if os.geteuid() == 0:
            return False
        tools = self.authorized_tools()
        if not tools:
            return False
        # Check availability before creating a pending request.
        if not here and terminal_command([]) is None:
            return False
        self.directory = Path(tempfile.mkdtemp(prefix="hubicg-system-tools-"))
        self.launched_at = time.monotonic()
        request = {"schema": "hubicg.station.system-tools/1", "engine": str(self.engine),
                   "tools": tools,
                   "repoDir": str(Path(self.repo_dir()).expanduser().resolve())}
        with (self.directory / "request.json").open("x", encoding="utf-8") as stream:
            json.dump(request, stream)
        if here:
            subprocess.run([sys.executable, str(Path(__file__).resolve()),
                            "--system-tools-helper", str(self.directory)], check=False)
            return True
        command = terminal_command([sys.executable, str(Path(__file__).resolve()),
                                    "--system-tools-helper", str(self.directory)])
        try:
            self.process = subprocess.Popen(command, env=fresh_env(), stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            (self.directory / "result.json").write_text('{"exitCode":4}', encoding="utf-8")
            return False
        return True


def markup(text: Any) -> str:
    return html.escape(str(text or ""), quote=False)


# --- frentes ---------------------------------------------------------------------------------------


class Frontend:
    """O que cada frente (zenity, kdialog, terminal) precisa saber mostrar."""

    name = "base"

    def __init__(self, texts: Texts) -> None:
        self.texts = texts
        self.system_tools: SystemToolsHelper | None = None

    def action_command(self, action: dict[str, Any]) -> str:
        if action.get("id") == "privilege-required":
            return self.system_tools.preview() if self.system_tools else "Motor da estação --only git,gh"
        return str(action.get("command") or "")

    def action_terminal(self, action: dict[str, Any]) -> bool:
        if action.get("id") == "privilege-required":
            return bool(self.system_tools and self.system_tools.launch())
        return open_terminal_with(str(action["command"]))

    def welcome(self, engine: Path) -> bool:
        raise NotImplementedError

    def run(self, title: str, engine_run: EngineRun, capture: str | None = None) -> RunState:
        raise NotImplementedError

    def environment(self, state: RunState, stderr: str) -> str:
        """Devolve 'next', 'recheck' ou 'quit'."""
        raise NotImplementedError

    def select(self, check: RunState, current: list[str], repo_dir: str) -> tuple[list[str], str] | None:
        raise NotImplementedError

    def actions(self, actions: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Conduz os pedidos; devolve as respostas, ou None para deixar para depois."""
        raise NotImplementedError

    def summary(self, state: RunState, stderr: str) -> str:
        """Devolve 'close', 'rerun' ou 'actions'."""
        raise NotImplementedError

    def fatal(self, message: str) -> None:
        raise NotImplementedError

    # Textos compartilhados pelas frentes.

    def summary_text(self, state: RunState, stderr: str) -> str:
        lines = [self.texts.exit_message(state.exit_code), ""]
        if state.gaps or state.recovered:
            lines += [self.texts["eventWarning"].format(state.gaps, len(state.recovered)), ""]
        groups = summary(self.texts, state)
        for group, items in groups.items():
            if not items:
                continue
            lines.append(f"{self.texts['groups'][group]} ({len(items)})")
            for item in items:
                lines.append(f"  - {item['label']}: {item['status']}. {item['message']}".rstrip())
            lines.append("")
        failures = [item["step"] for item in groups["failed"]]
        details = [str(state.step_data.get(step, {}).get("output") or "") for step in failures]
        details += [log["message"] for log in state.logs if log["level"] == "error"]
        if stderr.strip() and (failures or state.exit_code in (2, 130)):
            details += ["Saída de erro do instalador:", stderr.strip()[-2000:]]
        details = [detail for detail in details if detail]
        if details:
            lines += ["O que deu errado:", *details, ""]
        if state.log_file:
            lines.append(f"Log desta execução: {state.log_file}")
        lines.append("Rodar de novo é seguro: o instalador só faz o que faltar.")
        return "\n".join(lines)

    def auth_preview(self) -> str:
        return "\n".join("• " + text for text in self.texts["authPreview"].values())


class TerminalFrontend(Frontend):
    """Modo terminal: sem ambiente grafico, ou quando pedido com --frontend terminal."""

    name = "terminal"

    def __init__(self, texts: Texts, stdin: Any = None, stdout: Any = None) -> None:
        super().__init__(texts)
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout

    def say(self, text: str = "") -> None:
        self.stdout.write(text + "\n")
        self.stdout.flush()

    def ask(self, prompt: str) -> str:
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        if not line:
            raise EOFError
        return line.rstrip("\n")

    def yes(self, prompt: str, default: bool = True) -> bool:
        suffix = " [S/n] " if default else " [s/N] "
        while True:
            answer = self.ask(prompt + suffix).strip().lower()
            if not answer:
                return default
            if answer in ("s", "sim", "y", "yes"):
                return True
            if answer in ("n", "nao", "não", "no"):
                return False
            self.say("Responda s ou n.")

    def heading(self, text: str) -> None:
        self.say("")
        self.say(text)
        self.say("=" * len(text))

    def welcome(self, engine: Path) -> bool:
        self.heading(self.texts["welcome"]["title"])
        for paragraph in self.texts["welcome"]["body"]:
            self.say(paragraph)
        self.say(f"Instalador usado: {engine}")
        return self.yes("Verificar o computador agora?")

    def run(self, title: str, engine_run: EngineRun, capture: str | None = None) -> RunState:
        self.heading(title)

        def on_event(state: RunState, event: dict[str, Any], kind: str) -> None:
            step = event.get("step") or ""
            if kind == "step_start":
                self.say(f"[{state.index}/{state.total}] {self.texts.step(step)}…")
            elif kind == "step_end":
                self.say(f"      {self.texts.status(event['status'])['label']}: {event.get('message', '')}")
            elif kind == "log" and event.get("status") in ("warn", "error"):
                self.say(f"      Aviso: {event.get('message', '')}")
            elif kind == "action_required" and state.blocking:
                action = state.blocking
                self.say("")
                self.say(f"      {action['message']}")
                self.say(f"      Código: {action.get('code') or ''}")
                if action.get("url"):
                    self.say(f"      Página: {action['url']}")
                    if not action.get("browserOpenedByTool"):
                        open_url(action["url"])
                self.say("      Aguardando você concluir no navegador… (Ctrl+C interrompe)")
            elif kind == "action_resolved":
                self.say(f"      {event.get('message', '')}")

        try:
            return engine_run.run(on_event)
        except KeyboardInterrupt:
            engine_run.cancel()
            assert engine_run.process is not None
            engine_run.process.wait()
            engine_run.state.complete(130)
            return engine_run.state

    def environment(self, state: RunState, stderr: str) -> str:
        if state.exit_code in (2, 4):
            self.fatal(self.texts.exit_message(state.exit_code) + ("\n" + stderr.strip() if stderr.strip() else ""))
            return "quit"
        self.heading("Resultado da verificação")
        self.say(self.texts.exit_message(state.exit_code))
        for row in environment_rows(self.texts, state.environment):
            mark = {"ok": "ok", "info": "info", "warn": "AVISO", "error": "PROBLEMA"}[row["severity"]]
            self.say(f"  [{mark:^8}] {row['item']}: {row['value']}")
            if row["explain"] and row["severity"] in ("warn", "error"):
                self.say(f"             {row['explain']}")
        self.say("")
        for step in state.steps:
            if step != "environment" and step in state.status:
                self.say(f"  {self.texts.step(step)}: {self.texts.status(state.status[step])['label']}")
        while True:
            answer = self.ask("\n[A]vançar, [v]erificar de novo ou [c]ancelar? ").strip().lower() or "a"
            if answer.startswith("a"):
                return "next"
            if answer.startswith("v"):
                return "recheck"
            if answer.startswith("c"):
                return "quit"

    def select(self, check: RunState, current: list[str], repo_dir: str) -> tuple[list[str], str] | None:
        self.heading("O que instalar")
        options = [step for step in check.steps if step != "environment" and check.status.get(step) != "unsupported"]
        for number, step in enumerate(options, start=1):
            mark = "x" if step in current else " "
            status = self.texts.status(check.status.get(step, ""))["label"]
            self.say(f"  [{mark}] {number:2}. {self.texts.step(step)} — {status}")
        answer = self.ask("Enter para manter, ou os números a instalar (ex.: 1,2,5): ").strip()
        chosen = current
        if answer:
            picked = {int(part) for part in re.findall(r"\d+", answer)}
            chosen = [step for number, step in enumerate(options, start=1) if number in picked]
        if not chosen:
            self.say("Nenhuma etapa marcada.")
            return None
        folder = self.ask(f"Pasta do clone [{repo_dir}]: ").strip() or repo_dir
        self.say("")
        self.say("Como serão os logins:")
        self.say(self.auth_preview())
        self.say("Nenhuma senha ou token é digitado neste assistente.")
        return (chosen, folder) if self.yes("Instalar agora?") else None

    def actions(self, actions: list[dict[str, Any]]) -> dict[str, Any] | None:
        self.heading("Falta pouco: algumas coisas dependem de você")
        answers: dict[str, Any] = {}
        for number, action in enumerate(actions, start=1):
            guide = self.texts.action_guide(action)
            self.say("")
            self.say(f"{number}. {guide['title']}")
            self.say(f"   {guide['guide']}")
            self.say(f"   {action['message']}")
            kind = action["kind"]
            if kind in ("input", "confirm"):
                for answer in action["answers"]:
                    answers.update(self.ask_answer(answer))
            elif kind == "run_in_terminal" and action.get("command"):
                if action.get("id") == "privilege-required" and self.system_tools:
                    self.say(f"   Comando: {self.action_command(action)}")
                    if self.yes("Executar Git/GH neste terminal, como usuário normal?"):
                        self.system_tools.launch(here=True)
                    continue
                self.say(f"   Comando: {action['command']}")
                self.say("   Rode o comando num terminal (pode ser este, em outra aba) e siga as instruções dele.")
                self.ask("   Pressione Enter quando terminar…")
            else:
                if action.get("url"):
                    self.say(f"   Link: {action['url']}")
                if action.get("command"):
                    self.say(f"   Comando: {action['command']}")
                self.ask("   Pressione Enter quando estiver resolvido…")
        return answers if self.yes("\nVerificar e continuar?") else None

    def ask_answer(self, answer: dict[str, Any]) -> dict[str, Any]:
        key, kind, label = answer["key"], answer["type"], answer["label"]
        required = bool(answer.get("required"))
        if kind == "boolean":
            return {key: self.yes(f"   {label}?", default=answer.get("default") is not False)}
        while True:
            default = answer.get("default")
            value = self.ask(f"   {label}{f' [{default}]' if default else ''}: ").strip() or (default or "")
            if validate_answer(kind, value, required):
                return {key: value} if value else {}
            self.say("   Este e-mail não parece válido." if kind == "email" and value else "   Preencha este campo.")

    def summary(self, state: RunState, stderr: str) -> str:
        self.heading("Resumo")
        self.say(self.summary_text(state, stderr))
        options = "[C]oncluir, [r]odar de novo"
        if state.actions:
            options += " ou resolver as [p]endências"
        answer = self.ask(f"\n{options}? ").strip().lower() or "c"
        if answer.startswith("r"):
            return "rerun"
        if answer.startswith("p") and state.actions:
            return "actions"
        return "close"

    def fatal(self, message: str) -> None:
        self.heading("Não é possível continuar")
        self.say(message)


class DialogFrontend(Frontend):
    """Base de zenity e kdialog: executa o programa de dialogo e le a resposta."""

    program = ""

    def __init__(self, texts: Texts, capture: Callable[[str], None] | None = None) -> None:
        super().__init__(texts)
        self.capture = capture or (lambda name: None)

    def call(self, arguments: list[str], input_text: str | None = None) -> tuple[int, str]:
        result = subprocess.run([self.program, *arguments], input=input_text, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", check=False)
        return result.returncode, result.stdout.rstrip("\n")

    @staticmethod
    def close_dialogs(dialogs: list[subprocess.Popen[str]]) -> None:
        for dialog in dialogs:
            if dialog.poll() is None:
                dialog.terminate()
            try:
                dialog.wait(timeout=5)
            except subprocess.TimeoutExpired:
                dialog.kill()
                dialog.wait()
        dialogs.clear()


class ZenityFrontend(DialogFrontend):
    program = "zenity"
    name = "zenity"

    def base(self, title: str, width: int = 760, height: int | None = None) -> list[str]:
        args = [f"--title={self.texts['product']} — {title}", f"--width={width}"]
        if height:
            args.append(f"--height={height}")
        return args

    def welcome(self, engine: Path) -> bool:
        body = "\n\n".join(markup(p) for p in self.texts["welcome"]["body"])
        text = f"<big><b>{markup(self.texts['welcome']['title'])}</b></big>\n\n{body}\n\n" \
               f"<small>Instalador usado: {markup(engine)}</small>"
        code, _ = self.call(["--question", *self.base("Boas-vindas"), "--icon=system-software-install",
                             f"--text={text}", "--ok-label=Verificar o computador", "--cancel-label=Cancelar"])
        return code == 0

    def run(self, title: str, engine_run: EngineRun, capture: str | None = None) -> RunState:
        progress = subprocess.Popen(
            [self.program, "--progress", *self.base(title), f"--text={markup(title)}…", "--percentage=0",
             "--auto-close", "--cancel-label=Interromper"],
            stdin=subprocess.PIPE, text=True, encoding="utf-8",
        )
        code_dialog: list[subprocess.Popen[str]] = []
        finished = threading.Event()

        def watch_cancel() -> None:
            progress.wait()
            if not finished.is_set():
                engine_run.cancel()

        def send(line: str) -> None:
            try:
                assert progress.stdin is not None
                progress.stdin.write(line + "\n")
                progress.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass

        def on_event(state: RunState, event: dict[str, Any], kind: str) -> None:
            step = event.get("step") or ""
            if kind == "step_start":
                send(f"# Etapa {state.index} de {state.total}: {self.texts.step(step)}")
            elif kind == "progress" and event.get("message"):
                send(f"# {self.texts.step(step)}: {event['message']}")
            elif kind == "action_required" and state.blocking:
                action = state.blocking
                if action.get("url") and not action.get("browserOpenedByTool"):
                    open_url(action["url"])
                copied = copy_to_clipboard(str(action.get("code") or ""))
                code_dialog.append(self.show_code(action, copied))
                send("# Aguardando você concluir o login no navegador…")
            elif kind == "action_resolved":
                self.close_dialogs(code_dialog)
                send(f"# {event.get('message', '')}")
            percent = state.overall_percent()
            send(str(min(percent, 99)))

        threading.Thread(target=watch_cancel, daemon=True).start()
        try:
            state = engine_run.run(on_event)
        finally:
            finished.set()
            self.close_dialogs(code_dialog)
            send("100")
            try:
                assert progress.stdin is not None
                progress.stdin.close()
            except OSError:
                pass
            try:
                progress.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.close_dialogs([progress])
        return state

    def show_code(self, action: dict[str, Any], copied: bool) -> subprocess.Popen[str]:
        guide = self.texts.action_guide(action)["guide"]
        lines = [markup(action["message"]), "", f"<span size='xx-large' weight='bold'>{markup(action.get('code'))}</span>"]
        if copied:
            lines.append("O código já está na área de transferência.")
        if action.get("url"):
            lines.append(f"Página: {markup(action['url'])}")
        if action.get("timeoutSeconds"):
            lines.append(f"O código vale por {int(action['timeoutSeconds']) // 60} minutos.")
        lines += ["", markup(guide), "", "O instalador continua sozinho quando você autorizar."]
        return subprocess.Popen(
            [self.program, "--info", *self.base("Login no navegador", 620), "--icon=dialog-password",
             f"--text={chr(10).join(lines)}", "--ok-label=Ocultar este aviso"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
        )

    def environment(self, state: RunState, stderr: str) -> str:
        if state.exit_code in (2, 4):
            self.fatal(self.texts.exit_message(state.exit_code) + ("\n\n" + stderr.strip() if stderr.strip() else ""))
            return "quit"
        warnings = [log["message"] for log in state.logs if log["level"] in ("warn", "error")]
        text = f"<b>{markup(self.texts.exit_message(state.exit_code))}</b>"
        if state.gaps or state.recovered:
            text += "\n\n" + markup(self.texts["eventWarning"].format(state.gaps, len(state.recovered)))
        if warnings:
            text += "\n\n" + "\n".join("⚠ " + markup(w) for w in warnings)
        rows: list[str] = []
        severity = {"ok": "OK", "info": "Informação", "warn": "Aviso", "error": "Problema"}
        for row in environment_rows(self.texts, state.environment):
            rows += [row["item"], row["value"], severity[row["severity"]], row["explain"]]
        for step in state.steps:
            if step != "environment" and step in state.status:
                rows += [self.texts.step(step), self.texts.status(state.status[step])["label"], "Etapa",
                         state.messages.get(step, "")]
        code, out = self.call(["--list", *self.base("Verificação", 980, 620), f"--text={text}",
                               "--column=Item", "--column=Situação", "--column=Tipo", "--column=Explicação",
                               "--ok-label=Avançar", "--cancel-label=Cancelar",
                               "--extra-button=Verificar de novo", *rows])
        if out == "Verificar de novo":
            return "recheck"
        return "next" if code == 0 else "quit"

    def select(self, check: RunState, current: list[str], repo_dir: str) -> tuple[list[str], str] | None:
        rows: list[str] = []
        unsupported = []
        for step in check.steps:
            if step == "environment":
                continue
            if check.status.get(step) == "unsupported":
                unsupported.append(self.texts.step(step))
                continue
            rows += ["TRUE" if step in current else "FALSE", step, self.texts.step(step),
                     self.texts.status(check.status.get(step, ""))["label"]]
        text = "Marque as etapas que o instalador deve executar. O que já estiver pronto não é refeito."
        if unsupported:
            text += "\nNão se aplicam a este sistema: " + ", ".join(unsupported) + "."
        code, out = self.call(["--list", "--checklist", *self.base("Seleção", 760, 520), f"--text={markup(text)}",
                               "--column=Instalar", "--column=Id", "--column=Etapa", "--column=Situação",
                               "--hide-column=2", "--print-column=2", "--separator=,",
                               "--ok-label=Avançar", "--cancel-label=Cancelar", *rows])
        if code != 0:
            return None
        chosen = [step for step in out.split(",") if step]
        if not chosen:
            self.call(["--warning", *self.base("Seleção", 420), "--text=Marque pelo menos uma etapa."])
            return self.select(check, current, repo_dir)
        folder = repo_dir
        while True:
            text = (f"O repositório HubICG Community será clonado em:\n<b>{markup(folder)}</b>\n\n"
                    f"<b>Como serão os logins</b>\n{markup(self.auth_preview())}\n\n"
                    "Nenhuma senha ou token é digitado neste assistente.")
            code, out = self.call(["--question", *self.base("Pasta do clone", 700), f"--text={text}",
                                   "--ok-label=Instalar", "--cancel-label=Cancelar",
                                   "--extra-button=Escolher outra pasta"])
            if out == "Escolher outra pasta":
                picked_code, picked = self.call(["--file-selection", "--directory",
                                                 f"--title=Pasta onde o repositório será clonado",
                                                 f"--filename={Path(folder).parent}/"])
                if picked_code == 0 and picked:
                    folder = str(Path(picked) / "hubicg-community")
                continue
            return (chosen, folder) if code == 0 else None

    def actions(self, actions: list[dict[str, Any]]) -> dict[str, Any] | None:
        listing: list[str] = []
        for number, action in enumerate(actions, start=1):
            listing += [str(number), self.texts.action_guide(action)["title"], action["message"]]
        code, _ = self.call(["--list", *self.base("Pendências", 860, 420),
                             "--text=<b>Falta pouco: algumas coisas dependem de você.</b>\n"
                             "O assistente guia uma por uma. Depois, o instalador confere tudo de novo.",
                             "--column=Nº", "--column=Item", "--column=O que fazer",
                             "--ok-label=Resolver agora", "--cancel-label=Deixar para depois", *listing])
        if code != 0:
            return None
        answers: dict[str, Any] = {}
        for action in actions:
            answers.update(self.handle_action(action))
        return answers

    def handle_action(self, action: dict[str, Any]) -> dict[str, Any]:
        guide = self.texts.action_guide(action)
        title = guide["title"]
        intro = f"{markup(guide['guide'])}\n\n<b>{markup(action['message'])}</b>"
        kind = action["kind"]
        answers: dict[str, Any] = {}
        if kind == "input":
            fields = [a for a in action["answers"] if a["type"] != "boolean"]
            while fields:
                args = ["--forms", *self.base(title, 560), f"--text={intro}", "--separator=\t",
                        "--ok-label=Continuar", "--cancel-label=Pular"]
                args += [f"--add-entry={field['label']}" for field in fields]
                code, out = self.call(args)
                if code != 0:
                    break
                values = out.split("\t")
                invalid = [f["label"] for f, v in zip(fields, values) if not validate_answer(f["type"], v, bool(f.get("required")))]
                if invalid:
                    self.call(["--warning", *self.base(title, 460),
                               f"--text=Confira: {markup(', '.join(invalid))}. E-mail precisa ter o formato nome@dominio."])
                    continue
                answers.update({f["key"]: v.strip() for f, v in zip(fields, values) if v.strip()})
                break
            for field in [a for a in action["answers"] if a["type"] == "boolean"]:
                answers[field["key"]] = self.confirm(title, intro, field["label"])
        elif kind == "confirm":
            for field in action["answers"]:
                answers[field["key"]] = self.confirm(title, intro, field["label"])
        elif kind == "run_in_terminal" and action.get("command"):
            command = self.action_command(action)
            buttons = [] if action.get("id") == "privilege-required" else ["--extra-button=Copiar o comando"]
            while True:
                code, out = self.call(["--question", *self.base(title, 640),
                                       f"--text={intro}\n\nComando oficial: <tt>{markup(command)}</tt>",
                                       "--ok-label=Abrir o terminal", "--cancel-label=Agora não",
                                       *buttons])
                if out == "Copiar o comando":
                    copied = copy_to_clipboard(command)
                    self.call(["--info", *self.base(title, 420),
                               "--text=" + ("Comando copiado." if copied else f"Copie: <tt>{markup(command)}</tt>")])
                    continue
                if code == 0:
                    if self.action_terminal(action):
                        self.call(["--info", *self.base(title, 520),
                                   "--text=Siga as instruções no terminal que abriu. Quando terminar, clique em OK."])
                    else:
                        failure = ("Não foi possível abrir a etapa externa. Use uma sessão de usuário normal com terminal disponível. A instalação continua pendente."
                                   if action.get("id") == "privilege-required" else
                                   f"Não achei um terminal. Abra um e rode: <tt>{markup(command)}</tt>")
                        self.call(["--info", *self.base(title, 520), f"--text={failure}"])
                break
        else:
            extra = f"\n\n{markup(action['url'])}" if action.get("url") else ""
            code, _ = self.call(["--question", *self.base(title, 600), f"--text={intro}{extra}",
                                 "--ok-label=Abrir o link" if action.get("url") else "--ok-label=Entendi",
                                 "--cancel-label=Continuar"])
            if code == 0:
                open_url(action.get("url"))
        return answers

    def confirm(self, title: str, intro: str, label: str) -> bool:
        code, _ = self.call(["--question", *self.base(title, 600), f"--text={intro}\n\n{markup(label)}?",
                             "--ok-label=Sim", "--cancel-label=Não"])
        return code == 0

    def summary(self, state: RunState, stderr: str) -> str:
        rows: list[str] = []
        for group, items in summary(self.texts, state).items():
            for item in items:
                rows += [self.texts["groups"][group], item["label"], item["status"], item["message"]]
        text = f"<b>{markup(self.texts.exit_message(state.exit_code))}</b>"
        if state.gaps or state.recovered:
            text += "\n\n" + markup(self.texts["eventWarning"].format(state.gaps, len(state.recovered)))
        failed = self.summary_text(state, stderr).split("O que deu errado:")
        if len(failed) > 1:
            text += "\n\n<b>O que deu errado</b>\n" + markup(failed[1].split("Log desta execução")[0].strip()[:1500])
        if state.log_file:
            text += f"\n\nLog desta execução: <tt>{markup(state.log_file)}</tt>"
        args = ["--list", *self.base("Resumo", 980, 600), f"--text={text}", "--column=Grupo", "--column=Etapa",
                "--column=Situação", "--column=Detalhe", "--ok-label=Concluir", "--cancel-label=Fechar",
                "--extra-button=Rodar de novo"]
        if state.actions:
            args.append("--extra-button=Resolver as pendências")
        code, out = self.call([*args, *rows])
        if out == "Rodar de novo":
            return "rerun"
        if out == "Resolver as pendências":
            return "actions"
        return "close"

    def fatal(self, message: str) -> None:
        self.call(["--error", *self.base("Não é possível continuar", 560), f"--text={markup(message)}"])


class KdialogFrontend(DialogFrontend):
    """KDE: kdialog, com a barra de progresso controlada por D-Bus (qdbus) quando disponível."""

    program = "kdialog"
    name = "kdialog"

    def title(self, title: str) -> list[str]:
        return ["--title", f"{self.texts['product']} — {title}"]

    def qdbus(self) -> str | None:
        for name in ("qdbus", "qdbus6", "qdbus-qt6", "qdbus-qt5"):
            if which(name):
                return which(name)
        return None

    def welcome(self, engine: Path) -> bool:
        body = "\n\n".join(self.texts["welcome"]["body"])
        code, _ = self.call([*self.title("Boas-vindas"), "--yes-label", "Verificar o computador", "--no-label",
                             "Cancelar", "--yesno", f"{self.texts['welcome']['title']}\n\n{body}\n\nInstalador usado: {engine}"])
        return code == 0

    def run(self, title: str, engine_run: EngineRun, capture: str | None = None) -> RunState:
        qdbus = self.qdbus()
        handle: list[str] = []
        if qdbus:
            code, out = self.call([*self.title(title), "--progressbar", title, "100"])
            if code == 0 and len(out.split()) == 2:
                handle = out.split()
        if not handle:
            if which("zenity"):
                return ZenityFrontend(self.texts).run(title, engine_run, capture)
            if sys.stdin.isatty():
                return TerminalFrontend(self.texts).run(title, engine_run, capture)
            command = shlex.join([sys.executable, str(Path(__file__).resolve()), "--frontend", "terminal",
                                  "--engine", str(engine_run.engine)])
            self.fatal("Não foi possível abrir o progresso. Nada foi executado. Abra pelo terminal:\n" + command)
            engine_run.state.complete(4)
            return engine_run.state
        finished = threading.Event()
        code_dialog: list[subprocess.Popen[str]] = []

        def dbus(*arguments: str) -> str:
            if not handle or not qdbus:
                return ""
            result = subprocess.run([qdbus, *handle, *arguments], capture_output=True, text=True, check=False)
            return result.stdout.strip()

        def watch_cancel() -> None:
            while not finished.wait(0.5):
                if dbus("wasCancelled") == "true":
                    engine_run.cancel()
                    return

        def on_event(state: RunState, event: dict[str, Any], kind: str) -> None:
            step = event.get("step") or ""
            if kind == "step_start":
                dbus("setLabelText", f"Etapa {state.index} de {state.total}: {self.texts.step(step)}")
            elif kind == "action_required" and state.blocking:
                action = state.blocking
                if action.get("url") and not action.get("browserOpenedByTool"):
                    open_url(action["url"])
                copied = copy_to_clipboard(str(action.get("code") or ""))
                text = f"{action['message']}\n\nCódigo: {action.get('code')}\n"
                if copied:
                    text += "O código já está na área de transferência.\n"
                text += "\nO instalador continua sozinho quando você autorizar."
                code_dialog.append(subprocess.Popen([self.program, *self.title("Login no navegador"), "--msgbox", text]))
            elif kind == "action_resolved":
                self.close_dialogs(code_dialog)
            dbus("Set", "", "value", str(state.overall_percent()))

        if handle:
            threading.Thread(target=watch_cancel, daemon=True).start()
        try:
            state = engine_run.run(on_event)
        finally:
            finished.set()
            self.close_dialogs(code_dialog)
            dbus("close")
        return state

    def textbox(self, title: str, text: str) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write(text)
        try:
            self.call([*self.title(title), "--textbox", handle.name, "860", "560"])
        finally:
            os.unlink(handle.name)

    def environment(self, state: RunState, stderr: str) -> str:
        if state.exit_code in (2, 4):
            self.fatal(self.texts.exit_message(state.exit_code) + ("\n\n" + stderr.strip() if stderr.strip() else ""))
            return "quit"
        severity = {"ok": "OK", "info": "Info", "warn": "AVISO", "error": "PROBLEMA"}
        lines = [self.texts.exit_message(state.exit_code), ""]
        lines += ["Aviso: " + log["message"] for log in state.logs if log["level"] in ("warn", "error")]
        for row in environment_rows(self.texts, state.environment):
            lines.append(f"[{severity[row['severity']]}] {row['item']}: {row['value']}")
            if row["explain"] and row["severity"] in ("warn", "error"):
                lines.append(f"      {row['explain']}")
        lines.append("")
        for step in state.steps:
            if step != "environment" and step in state.status:
                lines.append(f"{self.texts.step(step)}: {self.texts.status(state.status[step])['label']}")
        self.textbox("Verificação", "\n".join(lines))
        code, _ = self.call([*self.title("Verificação"), "--yes-label", "Avançar", "--no-label", "Verificar de novo",
                             "--cancel-label", "Cancelar", "--yesnocancel", "Continuar a instalação?"])
        return {0: "next", 1: "recheck"}.get(code, "quit")

    def select(self, check: RunState, current: list[str], repo_dir: str) -> tuple[list[str], str] | None:
        items: list[str] = []
        for step in check.steps:
            if step == "environment" or check.status.get(step) == "unsupported":
                continue
            status = self.texts.status(check.status.get(step, ""))["label"]
            items += [step, f"{self.texts.step(step)} — {status}", "on" if step in current else "off"]
        code, out = self.call([*self.title("Seleção"), "--separate-output", "--checklist",
                               "Marque as etapas que o instalador deve executar.", *items])
        if code != 0:
            return None
        chosen = [line for line in out.splitlines() if line]
        if not chosen:
            return None
        code, folder = self.call([*self.title("Pasta do clone"), "--getexistingdirectory", str(Path(repo_dir).parent)])
        folder = str(Path(folder) / "hubicg-community") if code == 0 and folder else repo_dir
        text = (f"O repositório será clonado em:\n{folder}\n\nComo serão os logins:\n{self.auth_preview()}\n\n"
                "Nenhuma senha ou token é digitado neste assistente.")
        code, _ = self.call([*self.title("Instalar"), "--yes-label", "Instalar", "--no-label", "Cancelar", "--yesno", text])
        return (chosen, folder) if code == 0 else None

    def actions(self, actions: list[dict[str, Any]]) -> dict[str, Any] | None:
        answers: dict[str, Any] = {}
        for action in actions:
            guide = self.texts.action_guide(action)
            intro = f"{guide['guide']}\n\n{action['message']}"
            kind = action["kind"]
            if kind == "input":
                for field in action["answers"]:
                    if field["type"] == "boolean":
                        answers[field["key"]] = self.call([*self.title(guide["title"]), "--yesno", f"{intro}\n\n{field['label']}?"])[0] == 0
                        continue
                    while True:
                        code, value = self.call([*self.title(guide["title"]), "--inputbox", f"{intro}\n\n{field['label']}:",
                                                 str(field.get("default") or "")])
                        if code != 0:
                            break
                        if validate_answer(field["type"], value, bool(field.get("required"))):
                            if value.strip():
                                answers[field["key"]] = value.strip()
                            break
                        self.call([*self.title(guide["title"]), "--sorry", "Valor inválido. E-mail precisa ter o formato nome@dominio."])
            elif kind == "confirm":
                for field in action["answers"]:
                    answers[field["key"]] = self.call([*self.title(guide["title"]), "--yes-label", "Sim", "--no-label", "Não",
                                                       "--yesno", f"{intro}\n\n{field['label']}?"])[0] == 0
            elif kind == "run_in_terminal" and action.get("command"):
                code, _ = self.call([*self.title(guide["title"]), "--yes-label", "Abrir o terminal", "--no-label", "Agora não",
                                     "--yesno", f"{intro}\n\nComando oficial: {self.action_command(action)}"])
                if code == 0:
                    opened = self.action_terminal(action)
                    self.call([*self.title(guide["title"]), "--msgbox",
                               "Siga as instruções no terminal. Quando terminar, clique em OK." if opened
                               else f"Não foi possível abrir o terminal como usuário normal. {self.action_command(action)}"])
            else:
                extra = f"\n\n{action['url']}" if action.get("url") else ""
                code, _ = self.call([*self.title(guide["title"]), "--yes-label", "Abrir o link" if action.get("url") else "Entendi",
                                     "--no-label", "Continuar", "--yesno", intro + extra])
                if code == 0:
                    open_url(action.get("url"))
        code, _ = self.call([*self.title("Pendências"), "--yes-label", "Verificar e continuar", "--no-label",
                             "Deixar para depois", "--yesno", "Pronto. O instalador vai conferir tudo de novo."])
        return answers if code == 0 else None

    def summary(self, state: RunState, stderr: str) -> str:
        self.textbox("Resumo", self.summary_text(state, stderr))
        if state.actions:
            code, _ = self.call([*self.title("Resumo"), "--yes-label", "Resolver as pendências", "--no-label",
                                 "Rodar de novo", "--cancel-label", "Concluir", "--yesnocancel", "E agora?"])
            return {0: "actions", 1: "rerun"}.get(code, "close")
        code, _ = self.call([*self.title("Resumo"), "--yes-label", "Concluir", "--no-label", "Rodar de novo",
                             "--yesno", self.texts.exit_message(state.exit_code)])
        return "rerun" if code == 1 else "close"

    def fatal(self, message: str) -> None:
        self.call([*self.title("Não é possível continuar"), "--error", message])


# --- o assistente ----------------------------------------------------------------------------------


class Wizard:
    """O mesmo fluxo da W1: verificar, escolher, instalar, pendencias, resumo e nova execucao."""

    def __init__(self, frontend: Frontend, engine: Path, texts: Texts) -> None:
        self.frontend = frontend
        self.engine = engine
        self.texts = texts
        self.check: RunState | None = None
        self.selection: list[str] = []
        self.repo_dir = ""
        self.session = Session()
        self.last: RunState | None = None
        self.system_tools = SystemToolsHelper(self.engine, lambda: self.repo_dir, lambda: self.selection)
        self.frontend.system_tools = self.system_tools

    def apply(self, answers: dict[str, Any] | None = None, new_session: bool = False) -> tuple[RunState, str]:
        if self.system_tools.pending():
            self.frontend.fatal(self.system_tools.reason)
            assert self.last is not None
            return self.last, "Etapa externa pendente; nenhum novo motor foi iniciado."
        if new_session:
            self.session = Session()
        answers_file = write_answers_file(answers) if answers else None
        # Selecao padrao vai sem --only, para o motor reportar "unsupported" e nao "skipped".
        only = [] if self.check and set(self.selection) == set(default_selection(self.check)) else self.selection
        try:
            run = EngineRun(self.engine, engine_arguments("apply", only, self.repo_dir, answers_file))
            state = self.frontend.run("Instalando e configurando", run)
        finally:
            if answers_file and os.path.exists(answers_file):
                os.unlink(answers_file)
        self.last = self.session.merge(self.texts, state)
        return state, run.stderr

    def start(self) -> int:
        if not self.engine.exists():
            self.frontend.fatal(f"O motor do instalador não foi encontrado em:\n{self.engine}\n\n"
                                "Baixe o pacote completo do instalador e tente de novo.")
            return 1
        if not self.frontend.welcome(self.engine):
            return 0
        while True:
            run = EngineRun(self.engine, engine_arguments("check"))
            self.check = self.frontend.run("Verificando o computador", run)
            choice = self.frontend.environment(self.check, run.stderr)
            if choice == "quit":
                return int(self.check.exit_code or 0) if self.check.exit_code in (2, 4) else 0
            if choice == "next":
                break
        self.selection = default_selection(self.check)
        self.repo_dir = self.check.repo_dir or str(Path.home() / "github" / "hubicg-community")
        picked = self.frontend.select(self.check, self.selection, self.repo_dir)
        if not picked:
            return 0
        self.selection, self.repo_dir = picked
        state, stderr = self.apply(new_session=True)
        offer_actions = True
        while True:
            assert self.last is not None
            if offer_actions and state.exit_code == 3 and state.actions:
                answers = self.frontend.actions(state.actions)
                if answers is not None:
                    state, stderr = self.apply(answers)
                    continue
            offer_actions = True
            choice = self.frontend.summary(self.last, stderr)
            if choice == "rerun":
                state, stderr = self.apply(new_session=True)
            elif choice == "actions" and self.last.actions:
                answers = self.frontend.actions(self.last.actions)
                if answers is None:
                    offer_actions = False
                else:
                    state, stderr = self.apply(answers)
            else:
                return int(self.last.exit_code or 0)


def choose_frontend(requested: str, texts: Texts) -> Frontend | None:
    """zenity por padrao; kdialog no KDE; terminal sem ambiente grafico ou sem ferramenta de dialogo."""
    graphical = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if requested == "terminal":
        return TerminalFrontend(texts)
    if requested == "zenity":
        return ZenityFrontend(texts) if which("zenity") else None
    if requested == "kdialog":
        return KdialogFrontend(texts) if which("kdialog") else None
    if graphical:
        kde = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        if kde and which("kdialog") and KdialogFrontend(texts).qdbus():
            return KdialogFrontend(texts)
        if which("zenity"):
            return ZenityFrontend(texts)
        if which("kdialog") and KdialogFrontend(texts).qdbus():
            return KdialogFrontend(texts)
    if sys.stdin.isatty():
        return TerminalFrontend(texts)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assistente do instalador da estação HubICG (Linux).")
    parser.add_argument("--engine", default=os.environ.get("HUBICG_STATION_ENGINE") or str(DEFAULT_ENGINE),
                        help="motor a conduzir (padrão: ../../hubicg-station.sh)")
    parser.add_argument("--frontend", choices=("auto", "zenity", "kdialog", "terminal"), default="auto")
    parser.add_argument("--system-tools-helper", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--system-tools-child", nargs=2, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.system_tools_child:
        return system_tools_child(Path(args.system_tools_child[0]), int(args.system_tools_child[1]))
    if args.system_tools_helper:
        return run_system_tools_helper(args.system_tools_helper)
    texts = Texts()
    frontend = choose_frontend(args.frontend, texts)
    if frontend is None:
        # Aberto por clique duplo, sem zenity/kdialog: reabre num terminal, no modo terminal.
        relaunch = terminal_command([sys.executable, str(Path(__file__).resolve()), "--engine", args.engine,
                                     "--frontend", "terminal"])
        if relaunch and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            subprocess.Popen(relaunch, start_new_session=True)
            return 0
        sys.stderr.write("Sem zenity, kdialog ou terminal interativo. Rode: "
                         f"{Path(__file__).name} --frontend terminal\n")
        return 1
    try:
        return Wizard(frontend, Path(args.engine).resolve(), texts).start()
    except (EOFError, KeyboardInterrupt):
        return 130


if __name__ == "__main__":
    sys.exit(main())
