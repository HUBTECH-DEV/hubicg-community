"""Instalador da estação (#80): gerador de agentes, verificação e idempotência.

Os motores rodam de verdade, mas contra ferramentas falsas (``station_fakes``):
o PATH do processo só enxerga os lançadores falsos e o mínimo do sistema, e
todo diretório que o motor escreve fica numa pasta temporária. Assim os testes
provam o que o motor executou e o que ele deixou de executar, sem instalar
nada na máquina que roda a suíte.

O motor PowerShell só roda no Windows; o motor bash, no Linux. A CI cobre os
dois na matriz de sistemas.

Cada execução de motor custa alguns segundos (um processo por ferramenta
falsa), e a suíte inteira leva minutos. Por isso os cenários dos motores rodam
só com ``HUBICG_STATION_ENGINE_TESTS=1`` (``make station-test`` e o workflow
``station-installer.yml``); os testes do gerador rodam sempre.
"""

from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

import build_station_agents  # noqa: E402

from tests.station_fakes.validate_events import validate_event, SchemaValidationError

MOTOR_PS1 = RAIZ / "installers" / "station" / "hubicg-station.ps1"
MOTOR_SH = RAIZ / "installers" / "station" / "hubicg-station.sh"
FAKE = RAIZ / "tests" / "station_fakes" / "fake_tool.py"
_AGENT_TEMP = tempfile.TemporaryDirectory(prefix="station-public-agents-")
AGENTES = Path(_AGENT_TEMP.name)
build_station_agents.export(AGENTES)
CONTRATO = json.loads(
    (RAIZ / "docs" / "schemas" / "station-event.schema.json").read_text(encoding="utf-8")
)

STATUS_OK = {"checked", "already", "unsupported", "skipped"}
STATUS_STEP_END = set(CONTRATO["allOf"][0]["then"]["properties"]["status"]["enum"])
TIPOS = set(CONTRATO["properties"]["type"]["enum"])
ENVELOPE = CONTRATO["required"]
CODIGO = "ABCD-1234"


# --- Gerador de agentes ---------------------------------------------------------


MOTORES = os.environ.get("HUBICG_STATION_ENGINE_TESTS") == "1"
SEM_MOTORES = "cenários dos motores desligados; rode com HUBICG_STATION_ENGINE_TESTS=1 (make station-test)"


class SchemaDeEventosTests(unittest.TestCase):
    def test_schema_condicional_rejeita_eventos_invalidos(self) -> None:
        event = {"schema": "hubicg.station.event/1", "runId": "teste", "seq": 1,
                 "ts": "2026-10-22T12:00:00Z", "type": "action_required", "step": "git-identity",
                 "status": "action_required", "message": "", "data": {"id": "git-identity", "kind": "input", "blocking": False}}
        validate_event(event)
        for change in ({"ts": "ontem"}, {"seq": True}, {"data": {"id": "x", "kind": "invalid", "blocking": False}},
                       {"data": {"id": "x", "kind": "input"}}, {"type": "run_end", "data": {"exitCode": 99, "steps": {}}}):
            with self.subTest(change=change), self.assertRaises(SchemaValidationError):
                validate_event({**event, **change})


@unittest.skipUnless(os.name != "nt" and shutil.which("awk"), "leitor POSIX awk")
class JsonBashTests(unittest.TestCase):
    def parse(self, text, key="git.name"):
        return subprocess.run(["awk", "-v", "mode=answers", "-v", f"key={key}", "-f",
                               str(MOTOR_SH.with_name("json-read.awk"))], input=text,
                              capture_output=True, text=True, encoding="utf-8", env={**os.environ, "LC_ALL": "C"})

    def test_unicode_aspas_barras_e_surrogate_pair(self):
        name = 'Jos\u00e9 "Teste" \\ \U0001f680'
        for ascii_only in (True, False):
            r = self.parse(json.dumps({"schema": "hubicg.station.answers/1", "answers": {"git.name": name}}, ensure_ascii=ascii_only))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, name)

    def test_rejeita_json_invalido_tipos_e_envelope(self):
        for text in ('{"schema":"hubicg.station.answers/1","answers":{"git.name":"\\uD800"}}',
                     '{"schema":"hubicg.station.answers/1","answers":{"git.name":false}}',
                     '{"schema":"hubicg.station.answers/1","answers":{"desktop.loginConfirmed":"false"}}',
                     '{"schema":"hubicg.station.answers/1","answers":{},}',
                     '{"schema":"hubicg.station.answers/1","answers":{}} lixo',
                     '{"schema":"hubicg.station.answers/1","answers":{"git.name":"a","git.name":"b"}}',
                     '{"schema":"hubicg.station.answers/1","answers":{"git.name":"\\u0000"}}',
                     '{"schema":"hubicg.station.answers/1"}'):
            with self.subTest(text=text):
                r = self.parse(text)
                self.assertEqual(r.returncode, 2, r)
                self.assertEqual(r.stdout, "")

    def test_chave_desconhecida_com_barra_nao_fabrica_resposta(self):
        for answers in ({}, {"git.name": "Legitima"}):
            doc = {"schema": "hubicg.station.answers/1", "answers": answers,
                   "answers/git.name": "Injetada", "answers~1git.name": "Outra"}
            r = self.parse(json.dumps(doc))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, answers.get("git.name", ""))


# --- Máquina falsa ------------------------------------------------------------------


ESSENCIAIS_POSIX = (
    "bash sh sed grep awk tr head tail date df dirname basename mkdir rm mv cp cat ls sort cmp "
    "mktemp sha256sum shasum env uname printenv install tee timeout sleep"
).split()


class Maquina:
    """Uma estação descartável: PATH, HOME, configuração do Claude e estado."""

    def __init__(self, motor: str, **estado: object) -> None:
        self.motor = motor
        self.desktop_mode = "installed"
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        self.bin = self.raiz / "bin"
        self.home = self.raiz / "home"
        self.config = self.raiz / "claude-config"
        self.repo = self.raiz / "github" / "hubicg-community"
        self.logs = self.raiz / "logs"
        self.estado_arquivo = self.raiz / "state" / "state.json"
        for pasta in (self.bin, self.home, self.logs, self.estado_arquivo.parent):
            pasta.mkdir(parents=True)
        self.estado = {"uid": 1000, "gh_access": True, "remote_head": "b" * 40}
        self.estado.update(estado)
        self.estado_arquivo.write_text(json.dumps(self.estado), encoding="utf-8")
        # curl falso sempre: no Windows, o System32 tem um curl.exe real, e um
        # teste sem o falso baixaria e rodaria o instalador real do Claude Code.
        self.instalar("curl", *(("id", "dpkg", "sudo") if motor != "ps1" else ()))
        if motor == "mac":
            self.instalar("uname", "sw_vers")
        self.execucoes = 0

    def fechar(self) -> None:
        self._tmp.cleanup()

    def instalar(self, *ferramentas: str) -> None:
        env = {**os.environ, "FAKE_STATE": str(self.estado_arquivo), "FAKE_BIN": str(self.bin)}
        for nome in ferramentas:
            subprocess.run([sys.executable, str(FAKE), "__install", nome], env=env, check=True)

    def ajustar(self, **mudancas: object) -> None:
        estado = json.loads(self.estado_arquivo.read_text(encoding="utf-8"))
        estado.update(mudancas)
        self.estado_arquivo.write_text(json.dumps(estado), encoding="utf-8")

    def ler_estado(self) -> dict:
        return json.loads(self.estado_arquivo.read_text(encoding="utf-8"))

    def chamadas(self) -> list[dict]:
        arquivo = self.estado_arquivo.with_name("calls.jsonl")
        if not arquivo.exists():
            return []
        return [json.loads(linha) for linha in arquivo.read_text(encoding="utf-8").splitlines()]

    def zerar_chamadas(self) -> None:
        self.estado_arquivo.with_name("calls.jsonl").unlink(missing_ok=True)

    def _path(self) -> str:
        if self.motor == "ps1":
            windir = os.environ.get("SystemRoot", r"C:\Windows")
            return os.pathsep.join(
                [str(self.bin), rf"{windir}\System32", windir, rf"{windir}\System32\WindowsPowerShell\v1.0"]
            )
        sysbin = self.raiz / "sysbin"
        if not sysbin.exists():
            sysbin.mkdir()
            for nome in ESSENCIAIS_POSIX:
                if self.motor == "mac" and nome == "timeout":
                    continue  # macOS ships no GNU timeout; exercise the watchdog
                origem = shutil.which(nome)
                if origem:
                    (sysbin / nome).symlink_to(origem)
        return os.pathsep.join([str(self.bin), str(sysbin)])

    def _garantir_que_downloads_sao_falsos(self) -> None:
        # Trava de segurança: o motor baixa e executa instaladores com curl. Se
        # o curl do PATH do teste não for o falso, o teste para antes de rodar.
        alvo = shutil.which("curl", path=self._path())
        if alvo is None or Path(alvo).parent != self.bin:
            raise AssertionError(f"curl do teste não é o falso: {alvo}")

    def rodar(self, *extras: str, modo: str = "apply", respostas: dict | None = None,
              tls: str | None = None, rede: bool = False) -> "Execucao":
        self.execucoes += 1
        log = self.logs / f"run-{self.execucoes}.jsonl"
        env = {
            "PATH": self._path(),
            "FAKE_STATE": str(self.estado_arquivo),
            "FAKE_BIN": str(self.bin),
            "FAKE_AGENTS_SOURCE": str(AGENTES),
            "HOME": str(self.home),
            "SHELL": "/bin/zsh" if self.motor == "mac" else "/bin/bash",
            "HUBICG_STATION_TEST_DESKTOP": self.desktop_mode,
            # Sem isto, o motor Windows junta ao PATH o PATH real do registro
            # depois de cada instalação e passa a enxergar as ferramentas reais.
            "HUBICG_STATION_TEST_ISOLATED": "1",
            "HUBICG_STATION_TEST_ROOT": str(self.raiz / "sysroot"),
        }
        if tls:
            env["HUBICG_STATION_TEST_TLS_ISSUER"] = tls
        args: list[str] = []
        arquivo_respostas = None
        if respostas is not None:
            arquivo_respostas = self.raiz / f"respostas-{self.execucoes}.json"
            arquivo_respostas.write_text(
                json.dumps({"schema": "hubicg.station.answers/1", "answers": respostas}), encoding="utf-8"
            )
        if self.motor == "ps1":
            for chave in ("SystemRoot", "windir", "TEMP", "TMP", "PATHEXT", "ComSpec", "SystemDrive"):
                if chave in os.environ:
                    env[chave] = os.environ[chave]
            env["USERPROFILE"] = str(self.home)
            env["LOCALAPPDATA"] = str(self.home / "AppData" / "Local")
            args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(MOTOR_PS1),
                    "-Json", "-NonInteractive", "-RepoDir", str(self.repo), "-ConfigDir", str(self.config),
                    "-LogFile", str(log)]
            args += {"check": ["-Check"], "plan": ["-WhatIf"], "apply": []}[modo]
            if not rede:
                args.append("-SkipNetwork")
            if arquivo_respostas:
                args += ["-AnswersFile", str(arquivo_respostas)]
        else:
            shell = "/bin/bash" if self.motor == "mac" and platform.system() == "Darwin" else "bash"
            args = [shell, str(MOTOR_SH), "--json", "--non-interactive", "--repo-dir", str(self.repo),
                    "--config-dir", str(self.config), "--log-file", str(log)]
            args += {"check": ["--check"], "plan": ["--dry-run"], "apply": []}[modo]
            if not rede:
                args.append("--skip-network")
            if arquivo_respostas:
                args += ["--answers-file", str(arquivo_respostas)]
        args += list(extras)
        self._garantir_que_downloads_sao_falsos()
        processo = subprocess.run(args, env=env, capture_output=True, text=True, encoding="utf-8",
                                  stdin=subprocess.DEVNULL, timeout=int(os.environ.get("STATION_TIMEOUT", "300")))
        return Execucao(processo, log)


class Execucao:
    def __init__(self, processo: subprocess.CompletedProcess, log: Path) -> None:
        self.codigo = processo.returncode
        self.stdout = processo.stdout
        self.stderr = processo.stderr
        self.log = log
        try:
            self.eventos = [json.loads(linha) for linha in processo.stdout.splitlines() if linha.strip()]
            for evento in self.eventos:
                validate_event(evento)
        except json.JSONDecodeError as erro:
            raise AssertionError(f"stdout fora do contrato: {erro}\n{processo.stdout}\n{processo.stderr}")

    def status(self) -> dict[str, str]:
        return {e["step"]: e["status"] for e in self.eventos if e["type"] == "step_end"}

    def fim(self, etapa: str) -> dict:
        return next(e for e in self.eventos if e["type"] == "step_end" and e["step"] == etapa)

    def acoes(self) -> list[dict]:
        return [e for e in self.eventos if e["type"] == "action_required"]

    def __repr__(self) -> str:
        return f"codigo={self.codigo}\nstatus={self.status()}\nstderr={self.stderr[-2000:]}"


MUTANTES = (
    ("winget", "install"), ("apt-get", "install"), ("dnf", "install"), ("git", "clone"),
    ("brew", "install"),
    ("gh", "login"), ("gh", "setup-git"), ("curl", "-o"),
)


def mutacoes(chamadas: list[dict]) -> list[dict]:
    achadas = [c for c in chamadas for ferramenta, marca in MUTANTES
               if c["tool"] == ferramenta and marca in c["args"]]
    achadas += [c for c in chamadas if c["tool"] == "git" and c["args"][:1] == ["config"]
                and len([a for a in c["args"][1:] if not a.startswith("--")]) == 2]
    return achadas


def fotografia(pasta: Path) -> dict[str, tuple[int, bytes]]:
    if not pasta.exists():
        return {}
    return {str(p.relative_to(pasta)): (p.stat().st_mtime_ns, p.read_bytes())
            for p in sorted(pasta.rglob("*")) if p.is_file()}


# --- Cenários comuns aos dois motores ----------------------------------------------


class CenariosDoMotor:
    motor = ""
    desktop_suportado = True

    def maquina(self, **estado: object) -> Maquina:
        m = Maquina(self.motor, **estado)
        self.addCleanup(m.fechar)
        return m

    def maquina_vazia(self) -> Maquina:
        m = self.maquina(gh_auth=False, claude_auth=False)
        m.instalar("winget" if self.motor == "ps1" else "brew" if self.motor == "mac" else "apt-get")
        return m

    def maquina_pronta(self) -> Maquina:
        m = self.maquina(gh_auth=True, claude_auth=True)
        m.instalar("git", "gh", "claude", "winget" if self.motor == "ps1" else "brew" if self.motor == "mac" else "apt-get")
        m.ajustar(git_config={
            "user.name": ["Pessoa Teste"], "user.email": ["pessoa@exemplo.com.br"],
            "credential.https://github.com.helper": ["", "!gh auth git-credential"],
        }, claude_config_dir=str(m.config))
        return m

    def respostas_completas(self) -> dict:
        return {"git.name": "Pessoa Teste", "git.email": "pessoa@exemplo.com.br",
                "desktop.loginConfirmed": True}

    # Contrato -------------------------------------------------------------------

    def assert_contrato(self, execucao: Execucao) -> None:
        eventos = execucao.eventos
        self.assertGreater(len(eventos), 2, execucao)
        self.assertEqual(eventos[0]["type"], "run_start")
        self.assertEqual(eventos[-1]["type"], "run_end")
        self.assertEqual(eventos[-1]["data"]["exitCode"], execucao.codigo)
        self.assertEqual([e["seq"] for e in eventos], list(range(1, len(eventos) + 1)))
        self.assertEqual(len({e["runId"] for e in eventos}), 1)
        inicio = eventos[0]["data"]
        for campo in CONTRATO["allOf"][4]["then"]["properties"]["data"]["required"]:
            self.assertIn(campo, inicio)
        etapas = inicio["steps"]
        self.assertEqual([e["step"] for e in eventos if e["type"] == "step_start"], etapas)
        self.assertEqual([e["step"] for e in eventos if e["type"] == "step_end"], etapas)
        for evento in eventos:
            validate_event(evento)
            for campo in ENVELOPE:
                self.assertIn(campo, evento)
            self.assertEqual(evento["schema"], "hubicg.station.event/1")
            self.assertIn(evento["type"], TIPOS)
            self.assertIsInstance(evento["data"], dict)
            if evento["type"] == "step_end":
                self.assertIn(evento["status"], STATUS_STEP_END)
            if evento["type"] == "log":
                self.assertIn(evento["status"], {"info", "warn", "error"})
            if evento["type"] == "action_required":
                for campo in ("id", "kind", "blocking"):
                    self.assertIn(campo, evento["data"])

    # Verificação de ambiente ----------------------------------------------------------

    def test_check_em_maquina_vazia_so_verifica(self) -> None:
        m = self.maquina_vazia()
        r = m.rodar(modo="check")
        self.assert_contrato(r)
        self.assertEqual(r.codigo, 5, r)
        status = r.status()
        self.assertEqual(status["environment"], "checked")
        for etapa in ("git", "gh", "claude-cli", "repo", "agents"):
            self.assertEqual(status[etapa], "missing", (etapa, r))
        self.assertEqual(mutacoes(m.chamadas()), [])
        self.assertFalse(m.repo.exists())
        self.assertFalse(m.config.exists())

    def test_relatorio_de_ambiente_tem_os_campos_do_contrato(self) -> None:
        m = self.maquina_pronta()
        dados = m.rodar(modo="check").fim("environment")["data"]
        for campo in ("os", "osVersion", "arch", "shell", "shellVersion", "admin", "sudo", "packageManager",
                      "diskFreeGB", "proxy", "tools", "network", "tls"):
            self.assertIn(campo, dados)
        self.assertEqual(dados["tools"]["git"], "2.47.1")
        self.assertEqual(dados["tools"]["gh"], "2.62.0")
        self.assertEqual(dados["network"], "skipped")

    def test_inspecao_tls_e_detectada_e_explicada_sem_desligar_verificacao(self) -> None:
        m = self.maquina_pronta()
        r = m.rodar(modo="check", tls="C=ZZ, O=Netskope Test, CN=ca.example.invalid", rede=True)
        ambiente = r.fim("environment")["data"]
        self.assertEqual(ambiente["tls"], "inspected")
        self.assertEqual(ambiente["network"]["github.com"]["verdict"], "inspected")
        avisos = " ".join(e["message"] for e in r.eventos if e["type"] == "log" and e["step"] == "environment")
        self.assertIn("NAO sera desligada", avisos)
        self.assertIn("NODE_EXTRA_CA_CERTS", avisos)

    def test_ca_publica_nao_e_confundida_com_inspecao(self) -> None:
        m = self.maquina_pronta()
        r = m.rodar(modo="check", tls="C=US, O=Sectigo Limited, CN=Sectigo ECC Domain Validation Secure Server CA", rede=True)
        self.assertEqual(r.fim("environment")["data"]["tls"], "direct")

    def test_simulacao_mostra_comandos_e_nao_altera_nada(self) -> None:
        m = self.maquina_vazia()
        r = m.rodar(modo="plan")
        self.assert_contrato(r)
        self.assertEqual(r.codigo, 5, r)
        self.assertEqual(r.status()["git"], "would_install")
        self.assertIn("command", r.fim("git")["data"])
        self.assertEqual(mutacoes(m.chamadas()), [])
        self.assertFalse(m.repo.exists())

    # Idempotência ------------------------------------------------------------------

    def test_instala_do_zero_e_a_segunda_execucao_nao_muda_nada(self) -> None:
        m = self.maquina_vazia()
        m.ajustar(claude_config_dir=str(m.config))
        primeira = m.rodar(respostas=self.respostas_completas())
        self.assert_contrato(primeira)
        # Única pendência: o login do Claude Code, que só a pessoa faz.
        self.assertEqual(primeira.codigo, 3, primeira)
        self.assertEqual([a["data"]["id"] for a in primeira.acoes() if a["data"]["id"] != "gh-login"], ["claude-login"])
        status = primeira.status()
        self.assertEqual(status["claude-cli-auth"], "action_required")
        for etapa in ("git", "gh", "claude-cli"):
            self.assertEqual(status[etapa], "installed", (etapa, primeira))
        # As versões são as das ferramentas falsas: nada real entrou no PATH.
        self.assertEqual(primeira.fim("git")["data"]["version"], "2.47.1")
        self.assertEqual(primeira.fim("gh")["data"]["version"], "2.62.0")
        self.assertEqual(primeira.fim("claude-cli")["data"]["version"], "2.1.300")
        self.assertEqual(status["git-identity"], "configured")
        self.assertEqual(status["gh-auth"], "configured")
        self.assertEqual(status["repo"], "installed")
        self.assertEqual(status["agents"], "installed")
        instalados = sorted(p.name for p in (m.config / "agents").glob("*.md"))
        self.assertEqual(instalados, sorted(p.name for p in AGENTES.glob("*.md")))

        antes = fotografia(m.config)
        m.zerar_chamadas()
        m.ajustar(claude_auth=True)  # a pessoa rodou "claude auth login"
        segunda = m.rodar(respostas=self.respostas_completas())
        self.assert_contrato(segunda)
        self.assertEqual(segunda.codigo, 0, segunda)
        for etapa, valor in segunda.status().items():
            self.assertIn(valor, STATUS_OK, (etapa, segunda))
        self.assertEqual(mutacoes(m.chamadas()), [])
        self.assertEqual(fotografia(m.config), antes, "a segunda execução tocou na configuração do Claude")
        self.assertEqual(segunda.fim("agents")["data"]["counts"]["already"], len(instalados))

    def test_login_do_gh_sem_terminal_repassa_o_codigo_e_nao_o_grava(self) -> None:
        m = self.maquina_pronta()
        m.ajustar(gh_auth=False)
        r = m.rodar(respostas=self.respostas_completas())
        acao = next(a for a in r.acoes() if a["data"]["id"] == "gh-login")
        self.assertEqual(acao["data"]["kind"], "browser_code")
        self.assertTrue(acao["data"]["blocking"])
        self.assertEqual(acao["data"]["code"], CODIGO)
        self.assertEqual(acao["data"]["url"], "https://github.com/login/device")
        resolvido = next(e for e in r.eventos if e["type"] == "action_resolved")
        self.assertEqual(resolvido["status"], "completed")
        self.assertLess(acao["seq"], resolvido["seq"])
        self.assertLess(resolvido["seq"], r.fim("gh-auth")["seq"])
        self.assertEqual(r.status()["gh-auth"], "configured")
        self.assertIn(CODIGO, r.stdout)
        self.assertNotIn(CODIGO, r.log.read_text(encoding="utf-8"))

    def test_nada_de_identidade_da_conta_claude_sai_do_motor(self) -> None:
        m = self.maquina_pronta()
        r = m.rodar(modo="check")
        for texto in (r.stdout, r.log.read_text(encoding="utf-8")):
            self.assertNotIn("pessoa@exemplo.com.br\"", texto.replace("Pessoa Teste", ""))
            self.assertNotIn("Organizacao Secreta", texto)
        self.assertNotIn("gho_", r.stdout)

    # Pedidos de ação --------------------------------------------------------------

    def test_identidade_vazia_sem_resposta_vira_pedido_de_input(self) -> None:
        m = self.maquina_pronta()
        m.ajustar(git_config={"credential.https://github.com.helper": ["!gh auth git-credential"]})
        r = m.rodar(respostas={"desktop.loginConfirmed": True})
        self.assert_contrato(r)
        self.assertEqual(r.codigo, 3, r)
        acao = next(a for a in r.acoes() if a["data"]["id"] == "git-identity")
        self.assertEqual(acao["data"]["kind"], "input")
        self.assertFalse(acao["data"]["blocking"])
        self.assertEqual([a["key"] for a in acao["data"]["answers"]], ["git.name", "git.email"])
        # O repositório não depende da identidade: segue mesmo com a pendência.
        self.assertEqual(r.status()["repo"], "installed")

    def test_email_invalido_pede_de_novo(self) -> None:
        m = self.maquina_pronta()
        m.ajustar(git_config={"user.name": ["Pessoa"], "credential.https://github.com.helper": ["!gh auth git-credential"]})
        r = m.rodar(respostas={"git.email": "sem-arroba", "desktop.loginConfirmed": True})
        acao = next(a for a in r.acoes() if a["data"]["id"] == "git-identity")
        self.assertIn("invalido", acao["message"])
        self.assertEqual([a["key"] for a in acao["data"]["answers"]], ["git.email"])

    def test_identidade_git_nao_aparece_nos_eventos_ou_logs(self) -> None:
        m = self.maquina_pronta()
        for configured in (True, False):
            if not configured:
                m.ajustar(git_config={})
            r = m.rodar("-Only" if self.motor == "ps1" else "--only", "git-identity",
                        respostas=self.respostas_completas())
            self.assertIn(r.status()["git-identity"], ("already", "configured"), r)
            for text in (r.stdout, r.log.read_text(encoding="utf-8")):
                self.assertNotIn("Pessoa Teste", text)
                self.assertNotIn("pessoa@exemplo.com.br", text)

    def test_nome_git_com_escapes_json_e_persistido_sem_corrupcao(self) -> None:
        m = self.maquina_pronta()
        m.ajustar(git_config={})
        name = 'Jos\u00e9 "Teste" \\ \U0001f680'
        r = m.rodar("-Only" if self.motor == "ps1" else "--only", "git-identity",
                    respostas={"git.name": name, "git.email": "pessoa@exemplo.com.br"})
        self.assertEqual(r.status()["git-identity"], "configured", r)
        self.assertEqual(m.ler_estado()["git_config"]["user.name"], [name])

    def test_sem_acesso_ao_repositorio_pede_acao_externa_e_bloqueia_o_clone(self) -> None:
        m = self.maquina_pronta()
        m.ajustar(gh_access=False)
        r = m.rodar(respostas=self.respostas_completas())
        self.assertEqual(r.codigo, 3, r)
        acao = next(a for a in r.acoes() if a["data"]["id"] == "repo-access")
        self.assertEqual(acao["data"]["kind"], "external")
        self.assertEqual(r.status()["repo"], "blocked")
        self.assertEqual(r.fim("repo")["data"]["blockedBy"], ["gh-auth"])
        self.assertEqual(r.status()["agents"], "blocked")

    def test_login_do_claude_sem_terminal_pede_run_in_terminal(self) -> None:
        m = self.maquina_pronta()
        m.ajustar(claude_auth=False)
        r = m.rodar(respostas=self.respostas_completas())
        acao = next(a for a in r.acoes() if a["data"]["id"] == "claude-login")
        self.assertEqual(acao["data"]["kind"], "run_in_terminal")
        self.assertEqual(acao["data"]["command"], "claude auth login")

    def test_sessao_do_claude_nao_verificavel_nao_abre_login(self) -> None:
        # Versão antiga sem "auth status" (ou erro, ou tempo esgotado) não é o
        # mesmo que "sem login": o motor não abre o fluxo de login por engano.
        m = self.maquina_pronta()
        m.ajustar(claude_without_auth_command=True)
        r = m.rodar(respostas=self.respostas_completas())
        acao = next(a for a in r.acoes() if a["data"]["id"] == "claude-auth-unverified")
        self.assertEqual(acao["data"]["kind"], "run_in_terminal")
        self.assertEqual(acao["data"]["command"], "claude auth status")
        self.assertFalse(any(c["tool"] == "claude" and "login" in c["args"] for c in m.chamadas()))
        self.assertEqual(m.rodar(modo="check").status()["claude-cli-auth"], "missing")

    def test_resposta_inconsistente_do_claude_nao_pede_login(self) -> None:
        m = self.maquina_pronta()
        for reply, code in ((True, 1), ("false", 0), (None, 0)):
            with self.subTest(reply=reply, code=code):
                m.ajustar(claude_auth_reply=reply, claude_auth_exit=code)
                r = m.rodar("-Only" if self.motor == "ps1" else "--only", "claude-cli-auth")
                self.assertEqual(r.codigo, 3, r)
                self.assertEqual(r.acoes()[0]["data"]["id"], "claude-auth-unverified")
                self.assertFalse(any(c["tool"] == "claude" and "login" in c["args"] for c in m.chamadas()))

    def test_json_auth_invalido_ou_aninhado_nao_pede_login(self) -> None:
        m = self.maquina_pronta()
        for raw in ('{"loggedIn":false', 'text "loggedIn":false',
                    '{"nested":{"loggedIn":false}}', '{"nested":{"loggedIn":true}}',
                    '{"loggedIn":false} trailing'):
            with self.subTest(raw=raw):
                m.ajustar(claude_auth_raw=raw)
                r = m.rodar("-Only" if self.motor == "ps1" else "--only", "claude-cli-auth")
                self.assertEqual(r.codigo, 3, r)
                self.assertEqual(r.acoes()[0]["data"]["id"], "claude-auth-unverified")
                self.assertFalse(any(c["tool"] == "claude" and "login" in c["args"] for c in m.chamadas()))

    def test_gravacao_do_git_que_falha_e_falha_e_nao_configured(self) -> None:
        m = self.maquina_pronta()
        m.ajustar(git_config={"credential.https://github.com.helper": ["!gh auth git-credential"]},
                  git_config_readonly=True)
        r = m.rodar(respostas=self.respostas_completas())
        self.assertEqual(r.status()["git-identity"], "failed", r)
        self.assertEqual(r.codigo, 1)

    def test_pasta_de_agentes_que_nao_pode_ser_criada_falha(self) -> None:
        m = self.maquina_pronta()
        m.config.mkdir(parents=True)
        (m.config / "agents").write_text("isto deveria ser uma pasta", encoding="utf-8")
        r = m.rodar(respostas=self.respostas_completas())
        self.assertEqual(r.status()["agents"], "failed", r)
        self.assertEqual(r.codigo, 1)
        self.assertFalse((m.config / ".hubicg-station.json").exists()
                         and "principal" in (m.config / ".hubicg-station.json").read_text(encoding="utf-8"))

    # Agentes ---------------------------------------------------------------------

    def test_export_ausente_pede_geracao_publica(self) -> None:
        m = self.maquina_pronta()
        args = ("-Only" if self.motor == "ps1" else "--only", "agents")
        r = m.rodar(*args)
        self.assertEqual(r.codigo, 3, r)
        self.assertEqual(r.status()["agents"], "action_required")
        action = next(a for a in r.acoes() if a["data"]["id"] == "agents-export")
        self.assertIn("scripts/build_station_agents.py", action["message"])
        self.assertFalse((m.config / "agents").exists())
        # The GUI uses this selected clone's default path, with no AgentsSource override.
        shutil.copytree(AGENTES, m.repo / ".hubicg" / "exports" / "station-agents")
        delivered = m.rodar(*args)
        self.assertEqual(delivered.codigo, 0, delivered)
        self.assertEqual(delivered.status()["agents"], "installed")
        self.assertEqual(sorted(path.name for path in (m.config / "agents").glob("*.md")),
                         sorted(path.name for path in AGENTES.glob("*.md")))

    def test_agente_que_nao_e_do_instalador_nunca_e_sobrescrito(self) -> None:
        m = self.maquina_pronta()
        alvo = m.config / "agents" / "principal-devops-engineer.md"
        alvo.parent.mkdir(parents=True)
        alvo.write_text("meu agente\n", encoding="utf-8")
        r = m.rodar(respostas=self.respostas_completas())
        self.assertEqual(r.codigo, 0, r)
        self.assertEqual(alvo.read_text(encoding="utf-8"), "meu agente\n")
        dados = r.fim("agents")["data"]
        self.assertEqual(dados["conflicts"], ["principal-devops-engineer.md"])
        self.assertEqual(dados["counts"]["conflict"], 1)

    def test_agente_alterado_depois_da_instalacao_e_mantido(self) -> None:
        m = self.maquina_pronta()
        m.rodar(respostas=self.respostas_completas())
        alvo = m.config / "agents" / "principal-agile-coach.md"
        alvo.write_text(alvo.read_text(encoding="utf-8") + "nota minha\n", encoding="utf-8")
        r = m.rodar(respostas=self.respostas_completas())
        self.assertIn("principal-agile-coach.md", r.fim("agents")["data"]["conflicts"])
        self.assertTrue(alvo.read_text(encoding="utf-8").endswith("nota minha\n"))

    def test_agente_que_saiu_da_biblioteca_e_removido_se_intacto(self) -> None:
        m = self.maquina_pronta()
        origem = m.raiz / "origem"
        shutil.copytree(AGENTES, origem)
        m.rodar("-AgentsSource" if self.motor == "ps1" else "--agents-source", str(origem),
                respostas=self.respostas_completas())
        (origem / "principal-agile-coach.md").unlink()
        r = m.rodar("-AgentsSource" if self.motor == "ps1" else "--agents-source", str(origem),
                    respostas=self.respostas_completas())
        self.assertEqual(r.fim("agents")["data"]["counts"]["removed"], 1)
        self.assertFalse((m.config / "agents" / "principal-agile-coach.md").exists())

    def test_origem_adulterada_nao_instala_nada(self) -> None:
        m = self.maquina_pronta()
        origem = m.raiz / "origem"
        shutil.copytree(AGENTES, origem)
        arquivo = origem / "principal-agile-coach.md"
        arquivo.write_bytes(arquivo.read_bytes() + b"injetado\n")
        r = m.rodar("-AgentsSource" if self.motor == "ps1" else "--agents-source", str(origem),
                    respostas=self.respostas_completas())
        self.assertEqual(r.status()["agents"], "failed", r)
        self.assertFalse((m.config / "agents").exists() and any((m.config / "agents").iterdir()))

    # Repositório --------------------------------------------------------------------

    def test_clone_com_alteracao_local_nao_recebe_pull(self) -> None:
        m = self.maquina_pronta()
        m.rodar(respostas=self.respostas_completas())
        m.ajustar(repo_dirty=True, remote_head="c" * 40)
        m.zerar_chamadas()
        r = m.rodar(respostas=self.respostas_completas())
        self.assertEqual(r.status()["repo"], "already")
        self.assertFalse(any(c["tool"] == "git" and "pull" in c["args"] for c in m.chamadas()))

    def test_atualiza_o_clone_por_avanco_rapido(self) -> None:
        m = self.maquina_pronta()
        m.rodar(respostas=self.respostas_completas())
        m.ajustar(remote_head="c" * 40)
        r = m.rodar(respostas=self.respostas_completas())
        self.assertEqual(r.status()["repo"], "updated")

    def test_pasta_do_clone_com_outro_conteudo_nao_e_tocada(self) -> None:
        m = self.maquina_pronta()
        m.repo.mkdir(parents=True)
        (m.repo / "nota.txt").write_text("meu", encoding="utf-8")
        r = m.rodar(respostas=self.respostas_completas())
        self.assertEqual(r.status()["repo"], "failed")
        self.assertEqual(sorted(p.name for p in m.repo.iterdir()), ["nota.txt"])

    # Uso -----------------------------------------------------------------------------

    def test_etapa_desconhecida_e_erro_de_uso(self) -> None:
        m = self.maquina_pronta()
        r = m.rodar("-Only" if self.motor == "ps1" else "--only", "nao-existe", modo="check")
        self.assertEqual(r.codigo, 2)
        self.assertEqual(r.eventos, [])

    def test_opcao_desconhecida_e_erro_de_uso(self) -> None:
        m = self.maquina_pronta()
        r = m.rodar("-NaoExiste" if self.motor == "ps1" else "--nao-existe", modo="check")
        self.assertEqual(r.codigo, 2)
        self.assertEqual(r.eventos, [])

    def test_only_roda_so_o_pedido_e_o_ambiente(self) -> None:
        m = self.maquina_pronta()
        r = m.rodar("-Only" if self.motor == "ps1" else "--only", "git,gh", modo="check")
        self.assert_contrato(r)
        status = r.status()
        self.assertEqual(status["environment"], "checked")
        self.assertEqual(status["git"], "already")
        self.assertEqual(status["repo"], "skipped")

    def test_claude_desktop(self) -> None:
        m = self.maquina_pronta()
        status = m.rodar(modo="check").status()
        if self.desktop_suportado:
            self.assertEqual(status["claude-desktop"], "already")
        else:
            self.assertEqual(status["claude-desktop"], "unsupported")
            self.assertEqual(status["claude-desktop-auth"], "unsupported")


@unittest.skipUnless(MOTORES, SEM_MOTORES)
@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "motor PowerShell roda no Windows")
class MotorWindowsTests(CenariosDoMotor, unittest.TestCase):
    motor = "ps1"

    def test_gh_stderr_eof_nao_remove_prazo(self) -> None:
        # Load only the function under test, never execute a real engine/login.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = root / "close_stderr.py"
            child.write_text(
                'import os, sys, time\n'
                'from pathlib import Path\n'
                'sys.stderr.write("one-time code: ABCD-1234\\nOpen this URL: https://github.com/login/device\\n")\n'
                'sys.stderr.flush()\nos.close(2)\n'
                'Path(__file__).with_suffix(".pid").write_text(str(os.getpid()))\n'
                'time.sleep(60)\n', encoding="utf-8")
            harness = root / "deadline.ps1"
            harness.write_text(r'''
param([string]$Engine, [string]$Python, [string]$ChildScript)
$ErrorActionPreference = 'Stop'
$ast = [Management.Automation.Language.Parser]::ParseFile($Engine, [ref]$null, [ref]$null)
$function = $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-GhDeviceLogin'}, $true)[0]
Invoke-Expression $function.Extent.Text
$script:events = New-Object Collections.ArrayList
function Find-Tool { param($Name) return $Python }
function Test-GhAuth { throw 'timeout must not query authentication' }
function Send-Event {
    param($Type, $Step, $Status, $Message, $Data)
    [void]$script:events.Add(@{ type=$Type; status=$Status; data=$Data })
}
function New-ToolStartInfo {
    param($Path, $Arguments)
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $Python
    $info.Arguments = '"' + $ChildScript + '"'
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    return $info
}
$clock = [Diagnostics.Stopwatch]::StartNew()
$result = Invoke-GhDeviceLogin -TimeoutSeconds 1
if ($result -ne $false -or $clock.Elapsed.TotalSeconds -gt 10) { throw 'deadline not enforced' }
$timeouts = @($script:events | Where-Object { $_.type -eq 'action_resolved' -and $_.status -eq 'timeout' })
if ($timeouts.Count -ne 1) { throw 'missing timeout event' }
$childPid = [int](Get-Content -LiteralPath ([IO.Path]::ChangeExtension($ChildScript, '.pid')))
for ($attempt=0; $attempt -lt 20; $attempt++) {
    if (-not (Get-Process -Id $childPid -ErrorAction SilentlyContinue)) { exit 0 }
    Start-Sleep -Milliseconds 50
}
throw 'login child still alive'
''', encoding="utf-8-sig")
            result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                     str(harness), "-Engine", str(MOTOR_PS1), "-Python", sys.executable,
                                     "-ChildScript", str(child)], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_arquivo_e_utf8_com_bom(self) -> None:
        self.assertTrue(MOTOR_PS1.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_inspecao_tls_pede_schannel_para_o_git(self) -> None:
        m = self.maquina_pronta()
        tls = "CN=ca.example.invalid, O=Netskope Test"
        r = m.rodar(respostas=self.respostas_completas(), tls=tls, rede=True)
        acao = next(a for a in r.acoes() if a["data"]["id"] == "git-system-cert-store")
        self.assertEqual(acao["data"]["kind"], "confirm")
        respostas = {**self.respostas_completas(), "git.useSystemCertStore": True}
        r = m.rodar(respostas=respostas, tls=tls, rede=True)
        self.assertEqual(r.status()["git"], "configured", r)
        self.assertEqual(m.ler_estado()["git_config"]["http.sslBackend"], ["schannel"])


@unittest.skipUnless(MOTORES, SEM_MOTORES)
@unittest.skipUnless(os.name != "nt" and shutil.which("bash"), "motor macOS com ferramentas falsas em POSIX")
class MotorMacTests(CenariosDoMotor, unittest.TestCase):
    """Darwin simulated on Linux; native /bin/bash 3.2 and BSD tools on macOS CI."""
    motor = "mac"

    def test_probe_auth_nao_persiste_identidade_e_limpa_apos_interrupcao(self):
        m = self.maquina_pronta()
        tmp = m.raiz / "probe-tmp"
        tmp.mkdir()
        source = MOTOR_SH.read_text()
        deadline = "mac_deadline() {" + source.split("mac_deadline() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
        probe = "bounded_mac_auth_probe() (" + source.split("bounded_mac_auth_probe() (", 1)[1].split("\n)\n", 1)[0] + "\n)\n"
        script = "set -u\nJSON_READER=" + shlex.quote(str(MOTOR_SH.with_name("json-read.awk"))) + "\n" + deadline + probe + "bounded_mac_auth_probe\n"
        env = {"PATH": m._path(), "HOME": str(m.home), "TMPDIR": str(tmp),
               "FAKE_STATE": str(m.estado_arquivo), "FAKE_BIN": str(m.bin)}
        shell = "/bin/bash" if platform.system() == "Darwin" else "bash"
        normal = subprocess.run([shell], input=script.encode(), env=env, capture_output=True, timeout=30)
        self.assertEqual(normal.returncode, 0, normal.stderr)
        self.assertEqual(set(json.loads(normal.stdout)), {"loggedIn", "authMethod", "configDirectory"})
        self.assertEqual(list(tmp.iterdir()), [])
        m.ajustar(claude_auth_delay_after_output=60)
        process = subprocess.Popen([shell], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=env, start_new_session=True)
        try:
            process.stdin.write(script.encode())
            process.stdin.close()
            process.stdin = None
            end = time.monotonic() + 15
            while time.monotonic() < end:
                try:
                    if m.ler_estado().get("auth_output_ready"):
                        break
                except json.JSONDecodeError:
                    pass
                time.sleep(0.1)
            else:
                self.fail("consulta falsa nao iniciou")
            for file in tmp.rglob("*"):
                if file.is_file():
                    contents = file.read_text(errors="replace")
                    self.assertNotIn("pessoa@exemplo.com.br", contents)
                    self.assertNotIn("Organizacao Secreta", contents)
            os.killpg(process.pid, signal.SIGTERM)
            process.communicate(timeout=10)
            self.assertEqual(list(tmp.iterdir()), [])
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()

    def test_auth_status_tem_limite_sem_gnu_timeout(self):
        m = self.maquina_pronta()
        m.ajustar(claude_auth_delay=60)
        r = m.rodar("--only", "claude-cli-auth")
        self.assertEqual(r.codigo, 3, r)
        self.assertEqual(r.acoes()[0]["data"]["id"], "claude-auth-unverified")
        self.assertIn("30 s", r.acoes()[0]["message"])
        self.assertFalse(any(c["tool"] == "claude" and "login" in c["args"] for c in m.chamadas()))

    def test_relatorio_identifica_macos_intel_e_arm(self):
        m = self.maquina_pronta()
        for arch in ("x86_64", "arm64"):
            m.ajustar(mac_arch=arch)
            r = m.rodar("--only", "environment", modo="check")
            self.assertEqual(r.eventos[0]["data"]["os"], "macos")
            self.assertEqual(r.fim("environment")["data"]["arch"], arch)

    def test_sem_homebrew_pede_acao_sem_instalacao_real(self):
        m = self.maquina(gh_auth=False)
        r = m.rodar("--only", "gh")
        self.assertEqual(r.codigo, 3, r)
        self.assertEqual(r.acoes()[0]["data"]["id"], "package-manager-missing")
        self.assertFalse(any(c["tool"] == "brew" and "install" in c["args"] for c in m.chamadas()))

    def test_desktop_ausente_instala_so_na_conta_e_nao_repete(self):
        m = self.maquina_pronta()
        m.desktop_mode = "isolated"
        first = m.rodar("--only", "claude-desktop,claude-desktop-auth", respostas={"desktop.loginConfirmed": True})
        self.assertEqual(first.codigo, 0, first)
        self.assertEqual(first.status()["claude-desktop"], "installed", first)
        self.assertTrue((m.home / "Applications" / "Claude.app").is_dir())
        before = fotografia(m.config)
        m.zerar_chamadas()
        second = m.rodar("--only", "claude-desktop,claude-desktop-auth")
        self.assertEqual(second.codigo, 0, second)
        self.assertEqual(second.status()["claude-desktop"], "already")
        self.assertEqual(second.status()["claude-desktop-auth"], "already")
        self.assertEqual(fotografia(m.config), before)
        self.assertFalse(any(c["tool"] == "brew" and "install" in c["args"] for c in m.chamadas()))

    def test_desktop_existente_nao_e_reinstalado_e_login_pede_confirmacao(self):
        m = self.maquina_pronta()
        r = m.rodar("--only", "claude-desktop,claude-desktop-auth")
        self.assertEqual(r.codigo, 3, r)
        self.assertEqual(r.status()["claude-desktop"], "already")
        self.assertEqual(r.acoes()[0]["data"]["id"], "desktop-login-confirm")
        self.assertFalse(any(c["tool"] == "brew" and "install" in c["args"] for c in m.chamadas()))

    def test_macos_antigo_termina_sem_etapas(self):
        m = self.maquina_pronta()
        m.ajustar(mac_version="12.7")
        r = m.rodar()
        self.assertEqual(r.codigo, 4, r)
        self.assertEqual(r.status(), {})


@unittest.skipUnless(MOTORES, SEM_MOTORES)
@unittest.skipUnless(platform.system() == "Linux" and shutil.which("bash"), "motor bash roda no Linux")
class MotorLinuxTests(CenariosDoMotor, unittest.TestCase):
    motor = "sh"
    desktop_suportado = False

    def test_falha_ao_persistir_path_nao_reporta_configured(self) -> None:
        m = self.maquina_pronta()
        local_bin = m.home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (m.bin / "claude").rename(local_bin / "claude")
        (m.home / ".bashrc").mkdir()
        r = m.rodar("--only", "claude-cli", respostas={"claude.addToPath": True})
        self.assertEqual(r.codigo, 1, r)
        self.assertEqual(r.status()["claude-cli"], "failed", r)
        self.assertNotIn("incluido no PATH", r.stdout)

    def test_sem_curl_nao_declara_confianca_tls(self) -> None:
        m = self.maquina_pronta()
        m.instalar("openssl")
        (m.bin / "curl").unlink()
        def no_downloads():
            self.assertIsNone(shutil.which("curl", path=m._path()))
        m._garantir_que_downloads_sao_falsos = no_downloads
        r = m.rodar("--only", "environment", modo="check", rede=True)
        self.assertEqual(r.codigo, 0, r)
        for host in r.fim("environment")["data"]["network"].values():
            self.assertIsNone(host["trusted"])

    def test_sem_timeout_nao_consulta_auth_sem_limite(self) -> None:
        m = self.maquina_pronta()
        m._path()  # cria o PATH isolado; remove apenas o link temporario
        (m.raiz / "sysbin" / "timeout").unlink(missing_ok=True)
        r = m.rodar("--only", "claude-cli-auth")
        self.assertEqual(r.codigo, 3, r)
        self.assertEqual(r.acoes()[0]["data"]["id"], "claude-auth-unverified")
        self.assertFalse(any(c["tool"] == "claude" and c["args"][:1] == ["auth"] for c in m.chamadas()))

    def test_falhas_de_copia_e_manifesto_nunca_reportam_sucesso(self) -> None:
        for tool, target in (("cp", "/agents/"), ("mv", "/agents/"), ("mv", ".hubicg-station.json")):
            with self.subTest(tool=tool, target=target):
                m = self.maquina_pronta()
                real = shutil.which(tool)
                wrapper = m.bin / tool
                wrapper.write_text(
                    f'#!/bin/sh\ncase "$*" in *"{target}"*) exit 1 ;; esac\nexec "{real}" "$@"\n',
                    encoding="utf-8",
                )
                wrapper.chmod(0o755)
                r = m.rodar("--only", "agents", "--agents-source", str(AGENTES))
                self.assertEqual(r.status()["agents"], "failed", r)
                self.assertEqual(r.codigo, 1, r)
                manifest = m.config / ".hubicg-station.json"
                if manifest.exists():
                    self.assertEqual(json.loads(manifest.read_text())["agents"], {})

    def test_falha_ao_remover_agente_mantem_registro_e_reporta_falha(self) -> None:
        m = self.maquina_pronta()
        origem = m.raiz / "origem"
        shutil.copytree(AGENTES, origem)
        args = ("--only", "agents", "--agents-source", str(origem))
        self.assertEqual(m.rodar(*args).codigo, 0)
        name = "principal-agile-coach.md"
        (origem / name).unlink()
        real = shutil.which("rm")
        wrapper = m.bin / "rm"
        wrapper.write_text(
            f'#!/bin/sh\ncase "$*" in *"/agents/"*) exit 1 ;; esac\nexec "{real}" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        r = m.rodar(*args)
        self.assertEqual(r.codigo, 1, r)
        self.assertEqual(r.status()["agents"], "failed", r)
        self.assertTrue((m.config / "agents" / name).is_file())
        self.assertIn(name, json.loads((m.config / ".hubicg-station.json").read_text())["agents"])

    def test_sem_sudo_utilizavel_pede_privilegio(self) -> None:
        m = self.maquina_vazia()
        m.ajustar(sudo_passwordless=False)
        r = m.rodar(respostas=self.respostas_completas())
        acao = next(a for a in r.acoes() if a["data"]["id"] == "privilege-required")
        self.assertEqual(acao["data"]["kind"], "external")
        self.assertEqual(r.status()["git"], "action_required")
        self.assertFalse(any(c["tool"] == "apt-get" and "install" in c["args"] for c in m.chamadas()))

    def test_repositorio_apt_do_gh_e_configurado_no_caminho_oficial(self) -> None:
        m = self.maquina_vazia()
        m.rodar(respostas=self.respostas_completas())
        lista = m.raiz / "sysroot" / "etc" / "apt" / "sources.list.d" / "github-cli.list"
        self.assertIn("https://cli.github.com/packages stable main", lista.read_text(encoding="utf-8"))
        self.assertIn("signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg", lista.read_text(encoding="utf-8"))

    def test_path_do_claude_so_muda_com_autorizacao(self) -> None:
        m = self.maquina_pronta()
        local_bin = m.home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (m.bin / "claude").rename(local_bin / "claude")
        r = m.rodar(respostas=self.respostas_completas())
        acao = next(a for a in r.acoes() if a["data"]["id"] == "claude-path")
        self.assertEqual(acao["data"]["kind"], "confirm")
        self.assertFalse((m.home / ".bashrc").exists())
        r = m.rodar(respostas={**self.respostas_completas(), "claude.addToPath": True})
        self.assertEqual(r.status()["claude-cli"], "configured", r)
        self.assertIn(".local/bin", (m.home / ".bashrc").read_text(encoding="utf-8"))
        r = m.rodar(respostas={**self.respostas_completas(), "claude.addToPath": True})
        self.assertEqual(r.status()["claude-cli"], "already", r)
        self.assertEqual((m.home / ".bashrc").read_text(encoding="utf-8").count("hubicg-station"), 1)


if __name__ == "__main__":
    unittest.main()
