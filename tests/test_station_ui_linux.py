"""Interface L1 (zenity, kdialog e terminal) do instalador da estacao, contra o motor simulado."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import shlex
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LINUX = ROOT / "installers" / "station" / "ui" / "linux"
SIMULATOR = ROOT / "tests" / "fixtures" / "station" / "simulated_engine.py"

spec = importlib.util.spec_from_file_location("hubicg_station_ui", LINUX / "hubicg_station_ui.py")
ui = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ui)


def syntax_bash(platform: str = sys.platform) -> str | None:
    if platform != "win32":
        return shutil.which("bash")
    # Windows/System32/bash.exe is a WSL launcher, not the native Git Bash parser.
    git = shutil.which("git")
    roots = list(Path(git).resolve().parents[:3]) if git else []
    roots += [Path(value) / "Git" for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")
              if (value := os.environ.get(key))]
    if local := os.environ.get("LOCALAPPDATA"):
        roots.append(Path(local) / "Programs" / "Git")
    for root in roots:
        for relative in ("bin/bash.exe", "usr/bin/bash.exe"):
            candidate = root / relative
            if candidate.is_file():
                return str(candidate)
    return None


def event(seq: int, type_: str, step: str = "", status: str = "", **data: object) -> dict:
    return {"schema": "hubicg.station.event/1", "runId": "r", "seq": seq, "ts": "2026-10-22T00:00:00Z",
            "type": type_, "step": step, "status": status, "message": "", "data": data}


class SimulatorEnvironment:
    """Isola o estado do motor simulado num diretorio temporario."""

    def __init__(self, os_name: str = "linux", scenario: str = "default") -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.dict(os.environ, {
            "HUBICG_STATION_SIM_STATE": str(Path(self.temp.name) / "state.json"),
            "HUBICG_STATION_SIM_OS": os_name,
            "HUBICG_STATION_SIM_SCENARIO": scenario,
            "HUBICG_STATION_SIM_CODE_WAIT": "0",
            "HUBICG_STATION_SIM_BROWSER_OPENED": "1",
        })

    def __enter__(self) -> Path:
        self.patch.start()
        return Path(self.temp.name)

    def __exit__(self, *exc: object) -> None:
        self.patch.stop()
        self.temp.cleanup()


class CoreTests(unittest.TestCase):
    def test_unknown_status_cannot_finish_successfully(self) -> None:
        state = ui.RunState()
        state.apply(event(1, "step_end", "agents", "future_status"))
        state.apply(event(2, "run_end", exitCode=0))
        self.assertEqual(state.complete(0), 1)
        self.assertEqual(ui.Texts().status(state.status["agents"])["group"], "failed")
        self.assertNotEqual(ui.Texts().exit_message(state.exit_code), ui.Texts().exit_message(0))

    def setUp(self) -> None:
        self.texts = ui.Texts()

    def test_parse_event_ignores_noise_and_tolerates_unknown_fields(self) -> None:
        self.assertIsNone(ui.parse_event(""))
        self.assertIsNone(ui.parse_event("texto"))
        self.assertIsNone(ui.parse_event('{"schema":"outro/1","type":"log"}'))
        parsed = ui.parse_event(json.dumps({**event(1, "log", "git", "warn"), "novo": True}))
        self.assertEqual(parsed["type"], "log")

    def test_status_and_exit_texts(self) -> None:
        self.assertEqual(self.texts.status("already")["label"], "Já estava")
        self.assertEqual(self.texts.status("status_novo")["group"], "failed")
        self.assertIn("77", self.texts.exit_message(77))
        guide = self.texts.action_guide({"id": "pedido-novo", "kind": "run_in_terminal"})
        self.assertEqual(guide["title"], self.texts["kinds"]["run_in_terminal"]["title"])

    def test_state_tracks_gaps_blocking_and_interruption(self) -> None:
        state = ui.RunState()
        state.apply(event(1, "run_start", mode="apply", os="linux", steps=["environment", "gh-auth"],
                          repoDir="/r", configDir="/c", logFile="/l", engine="x", contract=1, interactive=False))
        state.apply(event(3, "step_start", "gh-auth", index=2, total=2))
        state.apply(event(4, "action_required", "gh-auth", "action_required", id="gh-login",
                          kind="browser_code", blocking=True, code="ABCD-1234"))
        self.assertEqual(state.gaps, 1)
        self.assertEqual(state.blocking["code"], "ABCD-1234")
        state.apply(event(5, "action_resolved", "gh-auth", "completed", id="gh-login"))
        self.assertIsNone(state.blocking)
        self.assertEqual(state.complete(-15), 130)

    def test_arguments_answers_and_selection(self) -> None:
        self.assertEqual(ui.engine_arguments("check"), ["--check", "--json", "--non-interactive"])
        self.assertEqual(ui.engine_arguments("apply", ["git", "gh"], "/x y", "/a.json"),
                         ["--json", "--non-interactive", "--only", "git,gh", "--repo-dir", "/x y",
                          "--answers-file", "/a.json"])
        self.assertEqual(ui.engine_command(Path("/m/hubicg-station.sh"), ["--json"])[0], "bash")
        self.assertTrue(ui.validate_answer("email", "maria@exemplo.com.br", True))
        self.assertFalse(ui.validate_answer("email", "maria", True))
        self.assertFalse(ui.validate_answer("string", " ", True))
        with tempfile.TemporaryDirectory() as directory:
            path = ui.write_answers_file({"git.name": " Maria ", "desktop.loginConfirmed": True}, directory)
            document = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(document["schema"], "hubicg.station.answers/1")
            self.assertEqual(document["answers"]["git.name"], "Maria")
            if os.name == "posix":
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_missing_step_end_is_recovered_and_visible_in_summary(self) -> None:
        state = ui.RunState()
        state.apply(event(1, "run_start", steps=["git"]))
        state.apply(event(2, "step_start", "git", index=1, total=1))
        state.apply(event(4, "run_end", exitCode=0, steps={"git": "installed"}))
        self.assertEqual(state.gaps, 1)
        self.assertEqual(state.status["git"], "installed")
        self.assertEqual(state.recovered, ["git"])
        self.assertEqual(ui.summary(self.texts, state)["done"][0]["step"], "git")
        text = ui.TerminalFrontend(self.texts).summary_text(state, "")
        self.assertIn("Relatório incompleto", text)
        self.assertIn("detalhes indisponíveis", text)
        frontend = ui.ZenityFrontend(self.texts)
        with mock.patch.object(frontend, "call", return_value=(0, "")) as call:
            frontend.summary(state, "")
        self.assertTrue(any("Relatório incompleto" in arg for arg in call.call_args.args[0]))

    def test_environment_rows_explain_problems(self) -> None:
        rows = ui.environment_rows(self.texts, {
            "os": "linux", "osVersion": "24.04", "arch": "x86_64", "sudo": "absent", "packageManager": None,
            "diskFreeGB": 2.0, "proxy": {"HTTPS_PROXY": "http://***@proxy:8080"}, "tls": "inspected",
            "network": {"github.com": {"verdict": "unreachable"}}, "tools": {"git": None},
        })
        by_item = {row["item"]: row for row in rows}
        self.assertEqual(by_item["Sistema"]["value"], "Linux 24.04 (x86_64)")
        warnings = [row for row in rows if row["severity"] in ("warn", "error")]
        self.assertGreaterEqual(len(warnings), 5)
        self.assertTrue(all(row["explain"] for row in warnings))


class TerminalWizardTests(unittest.TestCase):
    """O fluxo inteiro da L1 no modo terminal, com respostas digitadas."""

    def run_wizard(self, typed: str, os_name: str = "linux", scenario: str = "default") -> tuple[int, str]:
        with SimulatorEnvironment(os_name, scenario) as state_dir:
            answers_dir = state_dir / "answers"
            answers_dir.mkdir()
            output = io.StringIO()
            frontend = ui.TerminalFrontend(ui.Texts(), stdin=io.StringIO(typed), stdout=output)
            wizard = ui.Wizard(frontend, SIMULATOR, ui.Texts())
            with mock.patch.object(ui.tempfile, "tempdir", str(answers_dir)):
                code = wizard.start()
            self.assertEqual(list(answers_dir.iterdir()), [], "o arquivo de respostas precisa ser apagado")
            return code, output.getvalue()

    def test_full_cycle_with_pending_actions_and_idempotent_rerun(self) -> None:
        typed = "\n".join([
            "s",                    # verificar o computador
            "a",                    # avancar
            "",                     # manter a selecao
            "/tmp/hubicg-teste",    # pasta do clone
            "s",                    # instalar
            "Maria Silva",          # git.name
            "maria",                # e-mail invalido: pergunta de novo
            "maria@exemplo.com.br",
            "s",                    # claude.addToPath
            "s",                    # verificar e continuar
            # claude-cli-auth so roda depois do PATH resolvido (dependencia): aparece na 2a rodada.
            "",                     # Enter depois do claude auth login
            "s",                    # verificar e continuar
            "r",                    # rodar de novo
            "c",                    # concluir
        ]) + "\n"
        code, output = self.run_wizard(typed)
        self.assertEqual(code, 0, output)
        self.assertIn("Este e-mail não parece válido.", output)
        self.assertIn("Código: ABCD-1234", output)
        self.assertIn("Claude Desktop", output)
        self.assertIn("Não se aplica a este sistema", output)
        resumes = output.split("Resumo\n======")
        self.assertEqual(len(resumes), 3)
        self.assertIn("Instalado ou configurado agora (8)", resumes[1])
        self.assertIn("Já estava pronto ou não se aplica (11)", resumes[2])

    def test_failure_is_explained_in_the_summary(self) -> None:
        typed = "s\na\n\n/tmp/hubicg-teste\ns\n\n\n\nn\nc\n"
        code, output = self.run_wizard(typed, scenario="fail")
        self.assertEqual(code, 1, output)
        self.assertIn("Falhou", output)
        self.assertIn("O que deu errado:", output)
        self.assertIn("schannel", output)

    def test_unsupported_system_stops_before_any_step(self) -> None:
        code, output = self.run_wizard("s\n", scenario="unsupported-os")
        self.assertEqual(code, 4)
        self.assertIn("Não é possível continuar", output)


class FrontendSelectionTests(unittest.TestCase):
    def test_kde_prefers_kdialog_and_no_display_falls_back_to_terminal(self) -> None:
        texts = ui.Texts()
        tools = {"zenity": "/usr/bin/zenity", "kdialog": "/usr/bin/kdialog", "qdbus": "/usr/bin/qdbus"}
        with mock.patch.object(ui, "which", side_effect=tools.get):
            with mock.patch.dict(os.environ, {"DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "KDE"}, clear=True):
                self.assertEqual(ui.choose_frontend("auto", texts).name, "kdialog")
            with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, clear=True):
                self.assertEqual(ui.choose_frontend("auto", texts).name, "zenity")
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(ui.sys.stdin, "isatty", return_value=True):
                self.assertEqual(ui.choose_frontend("auto", texts).name, "terminal")

    def test_kde_without_qdbus_uses_zenity_or_terminal(self) -> None:
        texts = ui.Texts()
        tools = {"zenity": "/usr/bin/zenity", "kdialog": "/usr/bin/kdialog"}
        with mock.patch.object(ui, "which", side_effect=tools.get), \
                mock.patch.dict(os.environ, {"DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "KDE"}, clear=True), \
                mock.patch.object(ui.sys.stdin, "isatty", return_value=True):
            self.assertEqual(ui.choose_frontend("auto", texts).name, "zenity")
            del tools["zenity"]
            self.assertEqual(ui.choose_frontend("auto", texts).name, "terminal")

    def test_kdialog_progress_failure_falls_back_before_starting_engine(self) -> None:
        texts = ui.Texts()
        tools = {"zenity": "/usr/bin/zenity", "kdialog": "/usr/bin/kdialog"}
        for qdbus, result in ((None, (0, "")), ("qdbus", (1, "")), ("qdbus", (0, "invalid"))):
            with self.subTest(qdbus=qdbus, result=result):
                frontend = ui.KdialogFrontend(texts)
                run = ui.EngineRun(SIMULATOR, [])
                with mock.patch.object(frontend, "qdbus", return_value=qdbus), \
                        mock.patch.object(frontend, "call", return_value=result), \
                        mock.patch.object(ui, "which", side_effect=tools.get), \
                        mock.patch.object(ui.ZenityFrontend, "run", return_value=run.state) as fallback, \
                        mock.patch.object(run, "run") as launch:
                    self.assertIs(frontend.run("Progresso", run), run.state)
                fallback.assert_called_once_with("Progresso", run, None)
                launch.assert_not_called()

        frontend = ui.KdialogFrontend(texts)
        run = ui.EngineRun(SIMULATOR, [])
        with mock.patch.object(frontend, "qdbus", return_value=None), \
                mock.patch.object(ui, "which", return_value=None), \
                mock.patch.object(ui.sys.stdin, "isatty", return_value=True), \
                mock.patch.object(ui.TerminalFrontend, "run", return_value=run.state) as fallback:
            self.assertIs(frontend.run("Progresso", run), run.state)
        fallback.assert_called_once_with("Progresso", run, None)

    def test_desktop_entry_exec_resolves_to_the_launcher(self) -> None:
        """Exec segue a especificacao .desktop: escape do valor, depois aspas do Exec."""
        entry = (LINUX / "hubicg-station.desktop").read_text(encoding="utf-8")
        exec_line = next(line[5:] for line in entry.splitlines() if line.startswith("Exec="))
        value = exec_line.replace("\\\\", "\\")
        arguments, current, quoted, index = [], "", False, 0
        while index < len(value):
            char = value[index]
            if quoted and char == "\\":
                index += 1
                current += value[index]
            elif char == '"':
                quoted = not quoted
            elif char == " " and not quoted:
                arguments.append(current)
                current = ""
            else:
                current += char
            index += 1
        arguments.append(current)
        self.assertEqual(arguments, ["sh", "-c", 'exec "$(dirname "$0")/hubicg-station-ui.sh"', "%k"])

    def test_launcher_shell_syntax(self) -> None:
        bash = syntax_bash()
        self.assertIsNotNone(bash, "Bash real não encontrado: Windows exige Git Bash instalado; "
                             f"demais plataformas exigem bash no PATH. git={shutil.which('git')!r}; "
                             f"bash do PATH={shutil.which('bash')!r}")
        script = (LINUX / "hubicg-station-ui.sh").relative_to(ROOT).as_posix()
        command = [bash, "-n", script]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0,
                         f"command={command!r}; exit={result.returncode}; "
                         f"stdout={result.stdout!r}; stderr={result.stderr!r}")

    def test_windows_syntax_bash_ignores_wsl_launcher_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Git with spaces"
            (root / "cmd").mkdir(parents=True)
            (root / "bin").mkdir()
            git = root / "cmd" / "git.exe"
            bash = root / "bin" / "bash.exe"
            bash.touch()
            with mock.patch.object(shutil, "which", side_effect=lambda name:
                                   str(git) if name == "git" else "C:/Windows/System32/bash.exe"):
                self.assertEqual(Path(syntax_bash("win32")).resolve(), bash.resolve())

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("gio"), "executor .desktop GIO Linux")
    def test_shortcut_in_percent_directory_executes_original_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "path %f with spaces"
            folder.mkdir()
            launcher = folder / "hubicg-station-ui.sh"
            shutil.copyfile(LINUX / launcher.name, launcher)
            launcher.chmod(0o755)
            environment = {**os.environ, "HOME": str(root), "XDG_DATA_HOME": str(root / "data")}
            result = subprocess.run(["sh", str(launcher), "--criar-atalho"], env=environment,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            marker = root / "called"
            launcher.write_text('#!/bin/sh\nprintf called > "' + str(marker) + '"\n', encoding="utf-8")
            entry = root / "data/applications/hubicg-station.desktop"
            self.assertIn("%%f", entry.read_text())
            launched = subprocess.run(["gio", "launch", str(entry)], env=environment,
                                      capture_output=True, text=True, timeout=10)
            self.assertEqual(launched.returncode, 0, launched.stderr)
            for _ in range(100):
                if marker.exists():
                    break
                time.sleep(0.02)
            self.assertEqual(marker.read_text(), "called")


@unittest.skipUnless(os.name == "posix", "grupos de processos requerem POSIX")
class EngineCleanupTests(unittest.TestCase):
    def assert_process_exited(self, stat: Path) -> None:
        try:
            snapshot = stat.read_text()
        except (FileNotFoundError, ProcessLookupError):
            return  # Ausência no open (ENOENT) ou desaparecimento durante read (ESRCH).
        self.assertEqual(snapshot.rsplit(") ", 1)[1].split()[0], "Z",
                         "filho continua executando depois do cancelamento")

    def test_exit_probe_handles_disappearance_without_hiding_live_process_or_errors(self) -> None:
        import errno

        stat = mock.Mock(spec=Path)
        # A leitura pode falhar mesmo quando um probe anterior encontrou o processo.
        stat.exists.return_value = True
        self.assertTrue(stat.exists())
        for error in (FileNotFoundError(errno.ENOENT, "processo terminou"),
                      ProcessLookupError(errno.ESRCH, "processo terminou durante read")):
            with self.subTest(disappearance=type(error).__name__):
                stat.read_text.reset_mock()
                stat.read_text.side_effect = error
                self.assert_process_exited(stat)
                stat.read_text.assert_called_once_with()

        stat.read_text.side_effect = None
        stat.read_text.return_value = "123 (child) Z 1 2 3"
        self.assert_process_exited(stat)
        for state in ("R", "S", "D", "T"):
            with self.subTest(state=state):
                stat.read_text.return_value = "123 (child) " + state + " 1 2 3"
                with self.assertRaises(AssertionError):
                    self.assert_process_exited(stat)
        for error in (PermissionError(errno.EACCES, "permissão negada"),
                      OSError(errno.EIO, "leitura não comprova término")):
            with self.subTest(error=type(error).__name__):
                stat.read_text.side_effect = error
                with self.assertRaises(type(error)):
                    self.assert_process_exited(stat)

    def test_cancel_before_start_does_not_launch_engine(self) -> None:
        run = ui.EngineRun(Path("unused.py"), [])
        run.cancel()
        with mock.patch.object(ui.subprocess, "Popen") as launch:
            self.assertEqual(run.run(lambda *args: None).exit_code, 130)
        launch.assert_not_called()

    def test_cancel_during_creation_and_ignored_sigterm_are_bounded(self) -> None:
        script = textwrap.dedent('''\
            import json, signal, subprocess, sys, time
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            child = subprocess.Popen([sys.executable, "-c",
                "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready', flush=True); time.sleep(60)"],
                stdout=subprocess.PIPE, text=True)
            child.stdout.readline()
            print(json.dumps({"schema": "hubicg.station.event/1", "type": "log",
                              "data": {"childPid": child.pid}}), flush=True)
            time.sleep(60)
        ''')
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / "engine.py"
            engine.write_text(script, encoding="utf-8")
            run = ui.EngineRun(engine, [])
            child_pids = []

            def cancel(state, event, kind):
                child_pids.append(event["data"]["childPid"])
                run.cancel()

            started = time.monotonic()
            self.assertEqual(run.run(cancel).exit_code, 130)
            self.assertLess(time.monotonic() - started, 8)
            self.assertIsNotNone(run.process.poll())
            self.assert_process_exited(Path(f"/proc/{child_pids[0]}/stat"))

            # Simula pedido recebido enquanto Popen ainda não entregou o processo ao responsável.
            run = ui.EngineRun(engine, [])
            real_popen = subprocess.Popen

            def launch(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                run.cancel()
                return process

            with mock.patch.object(ui.subprocess, "Popen", side_effect=launch):
                self.assertEqual(run.run(lambda *args: None).exit_code, 130)
            self.assertIsNotNone(run.process.poll())

    def test_callback_exception_and_interrupt_stop_engine_and_child(self) -> None:
        script = textwrap.dedent('''\
            import json, subprocess, sys, time
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            print(json.dumps({"schema": "hubicg.station.event/1", "type": "log",
                              "data": {"childPid": child.pid}}), flush=True)
            time.sleep(60)
        ''')
        for error in (RuntimeError, KeyboardInterrupt):
            with self.subTest(error=error.__name__), tempfile.TemporaryDirectory() as directory:
                engine = Path(directory) / "engine.py"
                engine.write_text(script, encoding="utf-8")
                run = ui.EngineRun(engine, [])
                child_pids = []

                def fail(state, event, kind):
                    child_pids.append(event["data"]["childPid"])
                    raise error("interrupcao de teste")

                with self.assertRaises(error):
                    run.run(fail)
                self.assertIsNotNone(run.process.poll())
                self.assertTrue(run.process.stdout.closed)
                self.assertTrue(run.process.stderr.closed)
                self.assertEqual(len(child_pids), 1)
                child_stat = Path(f"/proc/{child_pids[0]}/stat")
                deadline = time.monotonic() + 3
                while child_stat.exists() and time.monotonic() < deadline:
                    if child_stat.read_text().split(") ", 1)[1].startswith("Z"):
                        break
                    time.sleep(0.05)
                if child_stat.exists():
                    self.assertTrue(child_stat.read_text().split(") ", 1)[1].startswith("Z"),
                                    "filho continua executando depois da interrupcao")


FAKE_ZENITY = textwrap.dedent('''\
    #!/usr/bin/env python3
    """zenity falso: registra cada chamada e responde como uma pessoa que aceita os padroes."""
    import json, os, sys, time
    args = sys.argv[1:]
    log = os.environ["FAKE_ZENITY_LOG"]
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(args) + "\\n")
    def has(text):
        return any(text in arg for arg in args)
    if "--progress" in args:
        sys.stdin.read()
        sys.exit(0)
    if "--info" in args and has("Login no navegador"):
        time.sleep(30)
        sys.exit(0)
    if "--checklist" in args:
        rows = [a for a in args if not a.startswith("--")]
        print(",".join(rows[i + 1] for i in range(0, len(rows), 4) if rows[i] == "TRUE"))
        sys.exit(0)
    if "--forms" in args:
        print("Maria Silva\\tmaria@exemplo.com.br")
        sys.exit(0)
    if has("--ok-label=Abrir o terminal"):
        sys.exit(1)
    if "--list" in args and has("Resumo"):
        counter = log + ".resumos"
        seen = int(open(counter).read()) if os.path.exists(counter) else 0
        open(counter, "w").write(str(seen + 1))
        if seen == 0:
            print("Rodar de novo")
            sys.exit(1)
    sys.exit(0)
''')


@unittest.skipUnless(os.name == "posix", "zenity falso precisa de um executavel com shebang")
class ZenityWizardTests(unittest.TestCase):
    def test_full_cycle_through_zenity(self) -> None:
        with SimulatorEnvironment("linux") as state_dir:
            bin_dir = state_dir / "bin"
            bin_dir.mkdir()
            fake = bin_dir / "zenity"
            fake.write_text(FAKE_ZENITY, encoding="utf-8")
            fake.chmod(0o755)
            log = state_dir / "zenity.log"
            # 1 s de espera no browser_code: tempo para o aviso do codigo abrir antes de ser fechado.
            env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_ZENITY_LOG": str(log),
                   "HUBICG_STATION_SIM_CODE_WAIT": "1"}
            with mock.patch.dict(os.environ, env), mock.patch.object(ui, "open_url"), \
                    mock.patch.object(ui, "copy_to_clipboard", return_value=False):
                code = ui.Wizard(ui.ZenityFrontend(ui.Texts()), SIMULATOR, ui.Texts()).start()
            calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(code, 0)
        titles = [next(a for a in call if a.startswith("--title=")).split("— ")[-1] for call in calls if any(a.startswith("--title=") for a in call)]
        for expected in ("Boas-vindas", "Verificação", "Seleção", "Pasta do clone", "Login no navegador",
                         "Pendências", "Identidade do Git", "Comando claude no PATH", "Login no Claude Code", "Resumo"):
            self.assertIn(expected, titles)
        code_dialog = next(call for call in calls if "--title=Instalador da estação HubICG — Login no navegador" in call)
        self.assertTrue(any("ABCD-1234" in arg for arg in code_dialog))
        self.assertFalse(any("--hide-text" in arg or "--password" in arg for call in calls for arg in call))


@unittest.skipUnless(sys.platform == "linux", "helper requer /proc, subreaper e pidfd do Linux")
class SystemToolsHelperTests(unittest.TestCase):
    def test_event_command_is_ignored_and_pending_blocks_new_engine(self) -> None:
        frontend = ui.TerminalFrontend(ui.Texts(), stdout=io.StringIO())
        wizard = ui.Wizard(frontend, SIMULATOR, ui.Texts())
        wizard.repo_dir = "/tmp/clone with spaces"
        wizard.selection = ["git", "gh"]
        wizard.last = ui.RunState()
        wizard.last.exit_code = 3
        action = {"id": "privilege-required", "command": "sudo arbitrary --token secret"}
        with mock.patch.object(ui.os, "geteuid", return_value=1000), \
                mock.patch.object(ui, "terminal_command", side_effect=lambda args: ["terminal", *args]), \
                mock.patch.object(ui.subprocess, "Popen") as popen:
            popen.return_value.poll.return_value = None
            self.assertNotIn("arbitrary", frontend.action_command(action))
            self.assertTrue(frontend.action_terminal(action))
            directory = wizard.system_tools.directory
            self.addCleanup(shutil.rmtree, directory)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            request = json.loads((directory / "request.json").read_text())
            self.assertEqual(set(request), {"schema", "engine", "repoDir", "tools"})
            self.assertIn("--system-tools-helper", popen.call_args.args[0])
            self.assertNotIn("sudo", popen.call_args.args[0])
            self.assertTrue(frontend.action_terminal(action))
            self.assertEqual(popen.call_count, 1)
            with mock.patch.object(ui, "EngineRun") as engine:
                state, _ = wizard.apply(new_session=True)
                self.assertIs(state, wizard.last)
                self.assertEqual(state.exit_code, 3)
                engine.assert_not_called()
            (directory / "result.json").write_text('{"exitCode":0}')
            # Helper success is not installation success: re-run the real check/apply path.
            checked = ui.RunState()
            checked.exit_code = 3
            with mock.patch.object(frontend, "run", return_value=checked) as run, \
                    mock.patch.object(ui, "EngineRun"):
                state, _ = wizard.apply(new_session=True)
                run.assert_called_once()
                self.assertEqual(state.exit_code, 3)

    @unittest.skipIf(os.name != "posix" or getattr(os, "geteuid", lambda: 0)() == 0,
                     "executar como usuário normal para provar o TTY")
    def test_helper_inherits_real_tty_and_limits_arguments(self) -> None:
        for tools in (["git"], ["gh"], ["git", "gh"]):
            with self.subTest(tools=tools):
                self.check_helper_tty(tools)

    def check_helper_tty(self, tools: list[str]) -> None:
        import pty
        import signal
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            engine = directory / "fake engine.sh"
            capture = directory / "args"
            engine.write_text('test -t 0 && test -t 1 && test -t 2 || exit 9\n'
                              'printf "%s\\n" "$@" > "' + str(capture) + '"\n')
            request = {"schema": "hubicg.station.system-tools/1", "engine": str(engine),
                       "tools": tools,
                       "repoDir": str(directory / "clone with spaces"), "command": "sudo bad", "only": "all"}
            (directory / "request.json").write_text(json.dumps(request))
            pid, master = pty.fork()
            if pid == 0:
                os.execv(sys.executable, [sys.executable, str(LINUX / "hubicg_station_ui.py"),
                                         "--system-tools-helper", str(directory)])
            try:
                deadline = time.monotonic() + 10
                while True:
                    waited, status = os.waitpid(pid, os.WNOHANG)
                    if waited:
                        break
                    if time.monotonic() > deadline:
                        os.kill(pid, signal.SIGKILL)
                        os.waitpid(pid, 0)
                        self.fail("helper TTY não terminou")
                    time.sleep(0.05)
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
                args = capture.read_text().splitlines()
                self.assertEqual(args, ["--only", ",".join(tools), "--repo-dir", request["repoDir"],
                                       "--config-dir", str(directory / "config"),
                                       "--log-file", str(directory / "engine.jsonl")])
                self.assertEqual(json.loads((directory / "result.json").read_text())["exitCode"], 0)
            finally:
                os.close(master)

    @unittest.skipIf(os.name != "posix" or getattr(os, "geteuid", lambda: 0)() == 0, "usuário normal")
    def test_cancel_waits_for_child_and_preserves_state(self) -> None:
        import pty
        import signal
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            engine = directory / "fake.sh"
            engine.write_text("trap '' INT TERM\n(trap '' INT TERM; while :; do sleep 1; done) &\n"
                              'echo "$!" > "' + str(directory / "grandchild") + '"\nwait\n')
            (directory / "request.json").write_text(json.dumps({"schema": "hubicg.station.system-tools/1",
                "tools": ["git", "gh"], "engine": str(engine), "repoDir": str(directory / "clone")}))
            preserved = directory / "engine.jsonl"
            preserved.write_text("diagnóstico")
            pid, master = pty.fork()
            if pid == 0:
                os.execv(sys.executable, [sys.executable, str(LINUX / "hubicg_station_ui.py"),
                                         "--system-tools-helper", str(directory)])
            record = None
            try:
                deadline = time.monotonic() + 10
                while not (directory / "grandchild").exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue((directory / "grandchild").exists())
                record = json.loads((directory / "started").read_text())
                self.assertNotEqual(record["pgid"], pid)
                os.kill(pid, signal.SIGTERM)
                helper = ui.SystemToolsHelper(engine, lambda: str(directory / "clone"))
                helper.directory = directory
                self.assertTrue(helper.pending())
                deadline = time.monotonic() + 12
                while helper.pending() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertFalse(helper.pending(), "netos devem encerrar antes de liberar a GUI")
                self.assertFalse(ui.system_tools_group_alive(record))
                os.waitpid(pid, 0)
            finally:
                if record and ui.system_tools_group_alive(record):
                    os.killpg(record["pgid"], signal.SIGKILL)
                os.close(master)
            self.assertEqual(preserved.read_text(), "diagnóstico")
            self.assertEqual(json.loads((directory / "result.json").read_text())["exitCode"], 130)

    @unittest.skipIf(os.name != "posix" or getattr(os, "geteuid", lambda: 0)() == 0, "usuário normal")
    def test_abrupt_helper_death_keeps_live_group_pending_then_recovers(self) -> None:
        import pty
        import signal
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            engine = directory / "fake.sh"
            engine.write_text('echo ready > "' + str(directory / "ready") + '"\nsleep 60\n')
            (directory / "request.json").write_text(json.dumps({"schema": "hubicg.station.system-tools/1",
                "tools": ["git", "gh"], "engine": str(engine), "repoDir": str(directory / "clone")}))
            pid, master = pty.fork()
            if pid == 0:
                os.execv(sys.executable, [sys.executable, str(LINUX / "hubicg_station_ui.py"),
                                         "--system-tools-helper", str(directory)])
            record = None
            try:
                deadline = time.monotonic() + 10
                while not (directory / "ready").exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue((directory / "ready").exists())
                record = json.loads((directory / "started").read_text())
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                helper = ui.SystemToolsHelper(engine, lambda: str(directory / "clone"))
                helper.directory = directory
                # SIGHUP may end the group on session-leader death; if alive, never release it.
                if ui.system_tools_group_alive(record):
                    self.assertTrue(helper.pending())
                    self.assertFalse((directory / "result.json").exists())
                    os.killpg(record["pgid"], signal.SIGKILL)
                deadline = time.monotonic() + 5
                while ui.system_tools_group_alive(record) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(helper.pending(), "sem recibo de término não podemos excluir descendentes setsid")
                self.assertIn("supervisão", helper.reason)
                self.assertFalse((directory / "result.json").exists())
                # Only a different kernel boot proves every unobservable old process ended.
                record["bootId"] = "previous-boot"
                ui.atomic_helper_record(directory, record)
                self.assertFalse(helper.pending())
                self.assertEqual(json.loads((directory / "result.json").read_text())["exitCode"], 130)
                self.assertTrue((directory / "request.json").exists())
            finally:
                if record and ui.system_tools_group_alive(record):
                    os.killpg(record["pgid"], signal.SIGKILL)
                os.close(master)

    def test_root_or_missing_terminal_cannot_launch(self) -> None:
        helper = ui.SystemToolsHelper(SIMULATOR, lambda: "/tmp/clone")
        with mock.patch.object(ui.os, "geteuid", return_value=0), \
                mock.patch.object(ui.subprocess, "Popen") as popen:
            self.assertFalse(helper.launch())
            popen.assert_not_called()
        with mock.patch.object(ui.os, "geteuid", return_value=1000), \
                mock.patch.object(ui, "terminal_command", return_value=None):
            self.assertFalse(helper.launch())
        self.assertIsNone(helper.directory)

    @unittest.skipIf(os.name != "posix" or getattr(os, "geteuid", lambda: 0)() == 0, "usuário normal")
    def test_missing_start_expires_atomically_and_late_helper_cannot_install(self) -> None:
        import fcntl
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            helper = ui.SystemToolsHelper(SIMULATOR, lambda: str(directory / "clone"))
            helper.directory = directory
            helper.launched_at = time.monotonic() - 61
            helper.process = mock.Mock()
            helper.process.poll.return_value = 0  # daemonized terminal client is not the helper
            (directory / "request.json").write_text(json.dumps({"schema": "hubicg.station.system-tools/1",
                "tools": ["git"], "engine": str(SIMULATOR), "repoDir": str(directory / "clone")}))
            with (directory / "launch.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                self.assertTrue(helper.pending(), "a partida que detém o gate não pode ser cancelada")
            self.assertFalse(helper.pending())
            self.assertEqual(json.loads((directory / "result.json").read_text())["exitCode"], 4)
            with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                    mock.patch.object(sys.stdout, "isatty", return_value=True), \
                    mock.patch.object(ui, "claim_system_tools_terminal") as claim, \
                    mock.patch.object(ui.subprocess, "Popen") as popen:
                self.assertEqual(ui.run_system_tools_helper(directory), 4)
                claim.assert_not_called()
                popen.assert_not_called()
            self.assertFalse((directory / "started").exists())

    def test_initial_started_publication_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            def interrupted(path, *args, **kwargs):
                with path.open("w") as stream:
                    stream.write('{"pid":')
                raise OSError("partida interrompida")
            with mock.patch.object(Path, "write_text", interrupted):
                with self.assertRaises(OSError):
                    ui.atomic_helper_record(directory, {"pid": 1})
            self.assertFalse((directory / "started").exists())
            ui.atomic_helper_record(directory, {"pid": 1})
            self.assertEqual(json.loads((directory / "started").read_text()), {"pid": 1})

    @unittest.skipIf(os.name != "posix" or getattr(os, "geteuid", lambda: 0)() == 0, "usuário normal")
    def test_setsid_descendant_outlives_engine_and_remains_supervised(self) -> None:
        import pty
        import signal
        for cancel, missed_adoption in ((False, False), (True, False), (False, True)):
            with self.subTest(cancel=cancel, missed_adoption=missed_adoption), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                ready = directory / "escaped"
                worker = ("import os,signal,time; os.setsid(); "
                          "signal.signal(signal.SIGINT,signal.SIG_IGN); "
                          "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                          f"open({str(ready)!r},'w').write(str(os.getpid())); "
                          f"time.sleep({60 if cancel else 2})")
                engine = directory / "fake.sh"
                engine.write_text(f"{shlex.quote(sys.executable)} -c {shlex.quote(worker)} &\nexit 0\n")
                (directory / "request.json").write_text(json.dumps({"schema": "hubicg.station.system-tools/1",
                    "tools": ["git"], "engine": str(engine), "repoDir": str(directory / "clone")}))
                pid, master = pty.fork()
                if pid == 0:
                    if missed_adoption:
                        # Simulate children/stat enumeration losing a just-adopted orphan.
                        shim = (f"import sys; sys.path.insert(0,{str(LINUX)!r}); "
                                "import hubicg_station_ui as ui; ui.system_tools_descendants=lambda: {}; "
                                f"sys.exit(ui.main(['--system-tools-helper',{str(directory)!r}]))")
                        os.execv(sys.executable, [sys.executable, "-c", shim])
                    os.execv(sys.executable, [sys.executable, str(LINUX / "hubicg_station_ui.py"),
                                             "--system-tools-helper", str(directory)])
                escaped = None
                try:
                    deadline = time.monotonic() + 10
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertTrue(ready.exists())
                    escaped = int(ready.read_text())
                    record = json.loads((directory / "started").read_text())
                    self.assertNotEqual(os.getsid(escaped), record["sid"])
                    helper = ui.SystemToolsHelper(engine, lambda: str(directory / "clone"))
                    helper.directory = directory
                    time.sleep(0.2)  # original engine has exited, adopted setsid child still lives
                    self.assertTrue(helper.pending())
                    self.assertFalse((directory / "result.json").exists())
                    if cancel:
                        self.assertEqual(os.tcgetpgrp(master), pid, "foreground deve voltar ao supervisor")
                        os.write(master, b"\x03")  # actual terminal-generated SIGINT, not kill(helper)
                    deadline = time.monotonic() + 12
                    while not (directory / "result.json").exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertTrue((directory / "result.json").exists())
                    os.waitpid(pid, 0)
                    self.assertFalse(helper.pending())
                    self.assertEqual(json.loads((directory / "result.json").read_text())["exitCode"],
                                     130 if cancel else 0)
                    stat = Path(f"/proc/{escaped}/stat")
                    if stat.exists():
                        self.assertEqual(stat.read_text().rsplit(") ", 1)[1].split()[0], "Z")
                finally:
                    for owned in (escaped, pid):
                        if owned:
                            try:
                                os.kill(owned, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                    os.close(master)


if __name__ == "__main__":
    unittest.main()
