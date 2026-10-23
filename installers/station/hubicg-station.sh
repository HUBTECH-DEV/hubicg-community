#!/usr/bin/env bash
# HubICG station installer engine for Linux and macOS (issue #80).
#
# Checks the environment, then installs and configures Git, GitHub CLI, the
# HUBTECH-DEV/hubicg-community clone and Claude Code CLI, and installs the
# HubICG agents rendered from the role library into the Claude configuration
# directory. Claude Desktop is reported as unsupported on Linux.
#
# Idempotent: a second run changes nothing and reports "already" everywhere.
# It never asks for, reads, prints or stores a token, password or cookie.
#
# With --json every event is one JSON object per line on stdout. The contract
# shared with the graphical interfaces (#83) is
# docs/architecture/station-installer-engine.md.
#
# Written for bash 3.2 or later: no associative arrays, no ${var,,}.

set -u

ENGINE_VERSION="1.0.0"
EVENT_SCHEMA="hubicg.station.event/1"

MODE="apply"
JSON=0
NON_INTERACTIVE=0
ONLY=""
REPOSITORY="HUBTECH-DEV/hubicg-community"
REPO_DIR="${HOME}/github/hubicg-community"
CONFIG_DIR="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}"
ANSWERS_FILE=""
LOG_FILE=""
AGENTS_SOURCE=""
SKIP_NETWORK=0
ANSWER_GIT_NAME=""
ANSWER_GIT_EMAIL=""
ANSWER_DESKTOP=""
ANSWER_CERT_STORE=""
ANSWER_ADD_PATH=""
# Test seam: a prefix for the system paths the apt repository setup writes.
SYSROOT="${HUBICG_STATION_TEST_ROOT:-}"
ENGINE_DIR=$(cd "$(dirname "$0")" && pwd)
JSON_READER="$ENGINE_DIR/json-read.awk"
OS_NAME=$(uname -s)

usage_error() {
  printf 'Uso incorreto: %s\n' "$1" >&2
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --check) MODE="check" ;;
    --dry-run) [ "$MODE" = "check" ] || MODE="plan" ;;
    --json) JSON=1 ;;
    --non-interactive) NON_INTERACTIVE=1 ;;
    --only) [ $# -ge 2 ] || usage_error "--only exige um valor"; ONLY="$2"; shift ;;
    --only=*) ONLY="${1#*=}" ;;
    --repo-dir) [ $# -ge 2 ] || usage_error "--repo-dir exige um valor"; REPO_DIR="$2"; shift ;;
    --config-dir) [ $# -ge 2 ] || usage_error "--config-dir exige um valor"; CONFIG_DIR="$2"; shift ;;
    --answers-file) [ $# -ge 2 ] || usage_error "--answers-file exige um valor"; ANSWERS_FILE="$2"; shift ;;
    --log-file) [ $# -ge 2 ] || usage_error "--log-file exige um valor"; LOG_FILE="$2"; shift ;;
    --agents-source) [ $# -ge 2 ] || usage_error "--agents-source exige um valor"; AGENTS_SOURCE="$2"; shift ;;
    --git-name) [ $# -ge 2 ] || usage_error "--git-name exige um valor"; ANSWER_GIT_NAME="$2"; shift ;;
    --git-email) [ $# -ge 2 ] || usage_error "--git-email exige um valor"; ANSWER_GIT_EMAIL="$2"; shift ;;
    --confirm-desktop-login) ANSWER_DESKTOP="true" ;;
    --add-to-path) ANSWER_ADD_PATH="true" ;;
    --skip-network) SKIP_NETWORK=1 ;;
    --repository) [ $# -ge 2 ] || usage_error "--repository exige um valor"; REPOSITORY="$2"; shift ;;
    --contract-version) printf '%s\n' "$EVENT_SCHEMA"; exit 0 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) usage_error "opcao desconhecida: $1" ;;
  esac
  shift
done

ALL_STEPS="environment git git-identity gh gh-auth repo claude-cli claude-cli-auth claude-desktop claude-desktop-auth agents"
for wanted in $(printf '%s' "$ONLY" | tr ',' ' '); do
  case " $ALL_STEPS " in
    *" $wanted "*) ;;
    *) usage_error "etapa desconhecida: $wanted. Validas: $ALL_STEPS" ;;
  esac
done

INTERACTIVE=0
if [ "$NON_INTERACTIVE" -eq 0 ] && [ -t 0 ] && [ -t 1 -o -t 2 ]; then INTERACTIVE=1; fi
REPO_URL="https://github.com/${REPOSITORY}.git"
STATE_FILE="${CONFIG_DIR}/.hubicg-station.json"
AGENTS_DEFAULT=0
if [ -z "$AGENTS_SOURCE" ]; then AGENTS_DEFAULT=1; AGENTS_SOURCE="${REPO_DIR}/.hubicg/exports/station-agents"; fi
RUN_ID="$(date -u '+%Y%m%dT%H%M%SZ')-$(printf '%04x' $((RANDOM % 65536)))"
SEQ=0

# --- JSON helpers ----------------------------------------------------------------

json_str() {
  local s
  s=$(printf '%s' "$1" | tr -d '\000-\010\013\014\016-\037')
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=${s//$'\n'/\\n}
  s=${s//$'\r'/\\r}
  s=${s//$'\t'/\\t}
  printf '"%s"' "$s"
}

json_or_null() {
  if [ -n "$1" ]; then json_str "$1"; else printf 'null'; fi
}

# jobj key json key json ... -> {"key":json,...}; values are already JSON.
jobj() {
  local out="{" first=1
  while [ $# -ge 2 ]; do
    [ $first -eq 1 ] || out="${out},"
    out="${out}$(json_str "$1"):$2"
    first=0
    shift 2
  done
  printf '%s}' "$out"
}

protect_text() {
  printf '%s' "$1" | sed -E \
    -e 's#://[^@/[:space:]]+@#://***@#g' \
    -e 's/(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-ant-[A-Za-z0-9_-]{10,})/[redacted]/g' \
    -e 's/([Bb][Ee][Aa][Rr][Ee][Rr][[:space:]]+)[A-Za-z0-9._-]+/\1[redacted]/g'
}

limit_output() {
  protect_text "$1" | tail -c 4096
}

# --- Log -----------------------------------------------------------------------

if [ -z "$LOG_FILE" ]; then
  if [ "$OS_NAME" = "Darwin" ]; then LOG_DIR="${HOME}/Library/Logs/HubICG/station"
  else LOG_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/hubicg/station/logs"; fi
  LOG_FILE="${LOG_DIR}/station-${RUN_ID}.jsonl"
else
  LOG_DIR=$(dirname -- "$LOG_FILE")
fi
if mkdir -p -- "$LOG_DIR" 2>/dev/null; then
  ls -1t -- "$LOG_DIR"/station-*.jsonl 2>/dev/null | tail -n +20 | while IFS= read -r old; do rm -f -- "$old"; done
else
  LOG_FILE=""
fi

# --- Events ----------------------------------------------------------------------

emit() {
  # emit TYPE STEP STATUS MESSAGE DATA_JSON [DEVICE_CODE]
  local type=$1 step=$2 status=$3 message data=${5:-} code=${6:-}
  [ -n "$data" ] || data="{}"
  message=$(protect_text "$4")
  SEQ=$((SEQ + 1))
  local head line
  head="{\"schema\":$(json_str "$EVENT_SCHEMA"),\"runId\":$(json_str "$RUN_ID"),\"seq\":${SEQ},\"ts\":$(json_str "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"),\"type\":$(json_str "$type"),\"step\":$(json_str "$step"),\"status\":$(json_str "$status")"
  line="${head},\"message\":$(json_str "$message"),\"data\":${data}}"
  if [ -n "$LOG_FILE" ]; then
    if [ -n "$code" ]; then
      # The one-time device code goes to the interface, never to disk.
      local safe_message=${message//"$code"/[codigo omitido]}
      local safe_data=${data//"$code"/[omitido]}
      printf '%s\n' "${head},\"message\":$(json_str "$safe_message"),\"data\":${safe_data}}" >>"$LOG_FILE" 2>/dev/null
    else
      printf '%s\n' "$line" >>"$LOG_FILE" 2>/dev/null
    fi
  fi
  if [ "$JSON" -eq 1 ]; then
    printf '%s\n' "$line"
    return
  fi
  case "$type" in
    run_start) printf 'HubICG station %s - modo: %s\n' "$ENGINE_VERSION" "$MODE" ;;
    step_end) printf '[%s] %s: %s\n' "$step" "$status" "$message" ;;
    action_required) printf '[%s] ACAO NECESSARIA: %s\n' "$step" "$message" ;;
    log) printf '[%s] %s\n' "$step" "$message" ;;
    run_end) printf '%s\n' "$message"; [ -z "$LOG_FILE" ] || printf 'Log: %s\n' "$LOG_FILE" ;;
  esac
}

log_msg() { emit log "$1" "$2" "$3" "${4:-}"; }

answer_item() {
  jobj key "$(json_str "$1")" type "$(json_str "$2")" label "$(json_str "$3")" required true
}

request_action() {
  # request_action STEP ID KIND MESSAGE [COMMAND] [URL] [ANSWERS_JSON_ARRAY]
  local args
  args=(id "$(json_str "$2")" kind "$(json_str "$3")" blocking false)
  [ -z "${7:-}" ] || args+=(answers "$7")
  [ -z "${5:-}" ] || args+=(command "$(json_str "$5")")
  [ -z "${6:-}" ] || args+=(url "$(json_str "$6")")
  emit action_required "$1" action_required "$4" "$(jobj "${args[@]}")"
}

# Every step sets these three instead of printing, so events never run in a
# subshell and the sequence number stays continuous.
R_STATUS=""
R_MESSAGE=""
R_DATA="{}"
result() { R_STATUS=$1; R_MESSAGE=$2; R_DATA=${3:-}; [ -n "$R_DATA" ] || R_DATA="{}"; }

# --- Answers ---------------------------------------------------------------------

answer_from_file() {
  LC_ALL=C awk -v mode=answers -v key="$1" -f "$JSON_READER" "$ANSWERS_FILE"
}

ANSWER_WARNINGS=""
if [ -n "$ANSWERS_FILE" ]; then
  [ -r "$ANSWERS_FILE" ] || usage_error "arquivo de respostas ilegivel: $ANSWERS_FILE"
  LC_ALL=C awk -v mode=answers -f "$JSON_READER" "$ANSWERS_FILE" >/dev/null || usage_error "JSON de respostas invalido ou tipos/schema incorretos"
  [ -n "$ANSWER_GIT_NAME" ] || ANSWER_GIT_NAME=$(answer_from_file git.name)
  [ -n "$ANSWER_GIT_EMAIL" ] || ANSWER_GIT_EMAIL=$(answer_from_file git.email)
  [ -n "$ANSWER_DESKTOP" ] || ANSWER_DESKTOP=$(answer_from_file desktop.loginConfirmed)
  [ -n "$ANSWER_CERT_STORE" ] || ANSWER_CERT_STORE=$(answer_from_file git.useSystemCertStore)
  [ -n "$ANSWER_ADD_PATH" ] || ANSWER_ADD_PATH=$(answer_from_file claude.addToPath)
  ANSWER_WARNINGS=$(LC_ALL=C awk -v mode=warnings -f "$JSON_READER" "$ANSWERS_FILE")
fi

# --- Tools -----------------------------------------------------------------------

has() { command -v "$1" >/dev/null 2>&1; }

TOOL_OUT=""
TOOL_CODE=0
run_tool() {
  TOOL_OUT=$("$@" 2>&1)
  TOOL_CODE=$?
}

tool_version() {
  has "$1" || return 0
  # /usr/bin/git on a clean Mac is a launcher for the CLT installation GUI.
  # A check/dry-run must not launch that installer.
  if [ "$OS_NAME" = "Darwin" ] && [ "$1" = "git" ] && [ "$(command -v git)" = "/usr/bin/git" ]; then
    xcode-select -p >/dev/null 2>&1 || return 0
  fi
  local out
  out=$("$1" --version 2>/dev/null) || return 0
  printf '%s' "$out" | grep -Eo '[0-9]+(\.[0-9]+)+' | head -n 1
}

read_yes_no() {
  [ "$INTERACTIVE" -eq 1 ] || return 1
  local answer
  printf '%s [s/N] ' "$1" >&2
  read -r answer || return 1
  case "$answer" in s|S|sim|Sim|y|Y|yes) return 0 ;; esac
  return 1
}

UID_NOW=$(id -u)
SUDO_MODE="absent"
if [ "$UID_NOW" -eq 0 ]; then
  SUDO_MODE="root"
elif has sudo; then
  if sudo -n true >/dev/null 2>&1; then SUDO_MODE="passwordless"; else SUDO_MODE="password"; fi
fi

can_be_root() {
  case "$SUDO_MODE" in
    root|passwordless) return 0 ;;
    password) [ "$INTERACTIVE" -eq 1 ] && return 0 ;;
  esac
  return 1
}

as_root() {
  # The password, when sudo asks, goes from the person to sudo in the terminal.
  if [ "$SUDO_MODE" = "root" ]; then "$@"; else sudo "$@"; fi
}

PKG=""
if [ "$OS_NAME" = "Darwin" ]; then
  if ! has brew && [ "${HUBICG_STATION_TEST_ISOLATED:-}" != "1" ]; then
    for brew_bin in /opt/homebrew/bin /usr/local/bin; do
      if [ -x "$brew_bin/brew" ]; then PATH="$brew_bin:$PATH"; break; fi
    done
  fi
  has brew && PKG="brew"
elif has apt-get; then PKG="apt"; elif has dnf; then PKG="dnf"; fi

need_privilege() {
  if [ "$SUDO_MODE" = password ]; then
    local command
    printf -v command 'bash %q --only %q --repo-dir %q --config-dir %q' "$ENGINE_DIR/hubicg-station.sh" "$1" "$REPO_DIR" "$CONFIG_DIR"
    request_action "$1" privilege-required run_in_terminal \
      "Abra o terminal pelo botao da interface para executar somente esta etapa. O sudo pede a senha no terminal do sistema, nunca na interface ou no log. Ao terminar, volte e verifique de novo. Para interromper esta acao externa, use Ctrl+C no proprio terminal." "$command"
  else
    request_action "$1" privilege-required external \
      "Instalar pacotes exige privilegio de administrador. Use uma conta com sudo disponivel e verifique de novo."
  fi
  result action_required "privilegio de administrador necessario"
}

APT_UPDATED=0
pkg_install() {
  # pkg_install PACKAGE...; returns the package manager exit code.
  case "$PKG" in
    apt)
      if [ "$APT_UPDATED" -eq 0 ]; then as_root apt-get update -qq >/dev/null 2>&1; APT_UPDATED=1; fi
      run_tool as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@"
      ;;
    dnf) run_tool as_root dnf install -y -q "$@" ;;
    brew) run_tool env HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ANALYTICS=1 brew install "$@" ;;
    *) TOOL_CODE=127; TOOL_OUT="sem gerenciador de pacotes" ;;
  esac
  return $TOOL_CODE
}

pkg_command() {
  case "$PKG" in
    apt) printf 'sudo apt-get install -y %s' "$*" ;;
    dnf) printf 'sudo dnf install -y %s' "$*" ;;
    brew) printf 'brew install %s' "$*" ;;
    *) printf '(sem apt ou dnf)' ;;
  esac
}

download() {
  # download URL TARGET; verification stays on, with the system CA bundle.
  run_tool curl -fsSL --retry 2 -o "$2" "$1"
  return $TOOL_CODE
}

# macOS does not ship GNU timeout. This watchdog closes stdin, bounds a
# read-only probe and captures output in a private temporary directory.
mac_deadline() {
  local seconds=$1; shift
  local pid watcher code
  "$@" </dev/null & pid=$!
  (
    trap 'kill "${timer:-}" 2>/dev/null; exit 0' TERM
    sleep "$seconds" & timer=$!
    wait "$timer"
    kill -KILL "$pid" 2>/dev/null
  ) >/dev/null 2>&1 & watcher=$!
  wait "$pid"; code=$?
  kill "$watcher" 2>/dev/null
  wait "$watcher" 2>/dev/null
  if [ "$code" -eq 137 ]; then code=124; fi
  return "$code"
}

bounded_mac_probe() {
  local work code
  work=$(mktemp -d "${TMPDIR:-/tmp}/hubicg-probe.XXXXXX") || return 125
  mac_deadline "$@" >"$work/out" 2>/dev/null; code=$?
  cat "$work/out"
  rm -rf -- "$work"
  return "$code"
}

bounded_mac_auth_probe() (
  # Parse the official response in memory before any file write. The only
  # persisted fields are the contract's non-account-identifying allowlist.
  local work codes
  work=$(mktemp -d "${TMPDIR:-/tmp}/hubicg-auth.XXXXXX") || return 125
  trap 'rm -rf -- "$work"' EXIT
  trap 'exit 130' INT TERM HUP
  mac_deadline 30 claude auth status 2>/dev/null |
    LC_ALL=C awk -v mode=auth -f "$JSON_READER" >"$work/allowed"
  codes=("${PIPESTATUS[@]}")
  if [ "${codes[1]}" -ne 0 ]; then
    [ "${codes[0]}" -ne 124 ] || return 124
    return 125
  fi
  cat "$work/allowed"
  return "${codes[0]}"
)

# --- environment -----------------------------------------------------------------

INSPECTION_VENDORS='Netskope|goskope|Zscaler|Palo ?Alto|Fortinet|FortiGate|Umbrella|Forcepoint|Blue ?Coat|Symantec Web|McAfee Web|Skyhigh|Sophos|Check ?Point|Barracuda|Menlo|iboss|Cloudflare Gateway|Smoothwall|Kaspersky|ESET SSL'
PUBLIC_CAS='DigiCert|Sectigo|USERTrust|COMODO|GlobalSign|Let.s Encrypt|ISRG|Google Trust|GTS |Amazon|Microsoft|Entrust|GoDaddy|Starfield|Baltimore|IdenTrust|Certum|SSL\.com|QuoVadis|Buypass|Actalis|HARICA'
TLS="skipped"

tls_issuer() {
  if [ -n "${HUBICG_STATION_TEST_TLS_ISSUER:-}" ]; then printf '%s' "$HUBICG_STATION_TEST_TLS_ISSUER"; return 0; fi
  if has openssl; then
    local cert
    if has timeout; then
      cert=$(timeout 10 openssl s_client -connect "$1:443" -servername "$1" </dev/null 2>/dev/null)
    elif [ "$OS_NAME" = "Darwin" ]; then
      cert=$(bounded_mac_probe 10 openssl s_client -connect "$1:443" -servername "$1")
    else
      cert=$(openssl s_client -connect "$1:443" -servername "$1" </dev/null 2>/dev/null)
    fi
    printf '%s' "$cert" | openssl x509 -noout -issuer 2>/dev/null | sed 's/^issuer= *//'
    return 0
  fi
  has curl && curl -sv --max-time 10 -o /dev/null "https://$1" 2>&1 | sed -n 's/^\*[[:space:]]*issuer: //p' | head -n 1
}

tls_trusted() {
  # 0 trusted, 60 untrusted certificate, anything else unreachable.
  if [ -n "${HUBICG_STATION_TEST_TLS_ISSUER:-}" ]; then return 0; fi
  has curl || return 127
  curl -sS --max-time 10 -o /dev/null "https://$1" >/dev/null 2>&1
  local code=$?
  case $code in 0|22) return 0 ;; esac
  return $code
}

step_environment() {
  local os_name="linux" os_version="" arch shell_version free tools net warnings="" verdicts=""
  if [ "$OS_NAME" = "Darwin" ]; then
    os_name="macos"; os_version=$(sw_vers -productVersion)
  elif [ -r /etc/os-release ]; then
    os_version=$(. /etc/os-release && printf '%s %s' "${ID:-linux}" "${VERSION_ID:-}")
  fi
  arch=$(uname -m)
  shell_version="${BASH_VERSION:-}"
  free=$(df -Pk -- "$(dirname -- "$REPO_DIR")" 2>/dev/null | awk 'NR==2 {printf "%.1f", $4/1048576}')
  [ -n "$free" ] || free=$(df -Pk -- "$HOME" 2>/dev/null | awk 'NR==2 {printf "%.1f", $4/1048576}')

  local proxy_args=() name value
  for name in HTTPS_PROXY HTTP_PROXY NO_PROXY https_proxy http_proxy no_proxy; do
    value=$(printenv "$name" 2>/dev/null)
    [ -z "$value" ] || proxy_args+=("$name" "$(json_str "$(protect_text "$value")")")
  done
  local proxy="{}"
  [ ${#proxy_args[@]} -eq 0 ] || proxy=$(jobj "${proxy_args[@]}")

  local t v tool_args=()
  for t in git gh claude curl openssl apt-get dnf sudo brew; do
    v=$(tool_version "$t")
    if [ -z "$v" ] && has "$t"; then v="presente"; fi
    tool_args+=("$t" "$(json_or_null "$v")")
  done
  tools=$(jobj "${tool_args[@]}")

  [ -n "$PKG" ] || warnings="${warnings}Gerenciador de pacotes ausente (Homebrew no macOS; apt/dnf no Linux).|"
  has curl || warnings="${warnings}curl ausente: sera instalado pelo gerenciador de pacotes antes dos downloads.|"
  case "$SUDO_MODE" in absent) warnings="${warnings}sudo ausente: rode como root para instalar pacotes.|" ;; esac
  if [ -n "$free" ] && awk "BEGIN {exit !($free < 2)}"; then warnings="${warnings}Pouco espaco livre: ${free} GB (recomendado: 2 GB).|"; fi

  if [ "$SKIP_NETWORK" -eq 1 ]; then
    net='"skipped"'
  else
    local h issuer verdict trusted host_args=()
    for h in github.com api.github.com claude.ai api.anthropic.com downloads.claude.ai; do
      issuer=$(tls_issuer "$h")
      tls_trusted "$h"
      local code=$?
      if [ -z "$issuer" ] && [ $code -ne 0 ] && [ $code -ne 60 ]; then
        verdict="unreachable"; trusted="null"
        warnings="${warnings}Sem conexao com ${h}:443.|"
      else
        if printf '%s' "$issuer" | grep -Eq "$INSPECTION_VENDORS"; then verdict="inspected"
        elif [ -n "$issuer" ] && ! printf '%s' "$issuer" | grep -Eq "$PUBLIC_CAS"; then verdict="suspected"
        else verdict="direct"; fi
        if [ $code -eq 60 ]; then
          trusted=false
          warnings="${warnings}O certificado apresentado por ${h} nao e confiavel nesta maquina.|"
        elif [ $code -eq 0 ]; then
          trusted=true
        else
          trusted=null
          warnings="${warnings}Confianca TLS de ${h} nao verificada (codigo $code).|"
        fi
      fi
      verdicts="${verdicts} ${verdict}"
      host_args+=("$h" "$(jobj verdict "$(json_str "$verdict")" issuer "$(json_or_null "$issuer")" trusted "$trusted")")
    done
    net=$(jobj "${host_args[@]}")
    case "$verdicts" in
      *inspected*) TLS="inspected" ;;
      *suspected*) TLS="suspected" ;;
      *direct*) TLS="direct" ;;
      *) TLS="unreachable" ;;
    esac
  fi

  if [ "$TLS" = "inspected" ] || [ "$TLS" = "suspected" ]; then
    if [ "$OS_NAME" = "Darwin" ]; then
      log_msg environment warn "Inspecao TLS detectada. Peca ao time de seguranca a CA e as instrucoes para o Keychain e as ferramentas CLI; se necessario, configure NODE_EXTRA_CA_CERTS com o PEM. A verificacao TLS NAO sera desligada." "$(jobj tls "$(json_str "$TLS")")"
    else
      log_msg environment warn "A rede reassina o TLS com uma CA corporativa (inspecao TLS, como a do Netskope). A verificacao TLS NAO sera desligada. No Linux, git, gh e curl confiam no repositorio de CAs do sistema: instale o PEM da CA em /usr/local/share/ca-certificates e rode update-ca-certificates (Debian/Ubuntu) ou em /etc/pki/ca-trust/source/anchors e rode update-ca-trust (Fedora/RHEL). O Claude Code nativo tambem le o repositorio do sistema; so precisa de NODE_EXTRA_CA_CERTS (caminho do PEM) se a CA nao estiver nele. Peca o PEM da CA ao time de seguranca." "$(jobj tls "$(json_str "$TLS")")"
    fi
  fi
  local IFS='|' w
  for w in $warnings; do [ -z "$w" ] || log_msg environment warn "$w"; done
  unset IFS
  for w in $ANSWER_WARNINGS; do log_msg environment warn "Resposta desconhecida ignorada: $w"; done

  local admin=false
  [ "$UID_NOW" -ne 0 ] || admin=true
  local sudo_json
  case "$SUDO_MODE" in root) sudo_json='"passwordless"' ;; *) sudo_json=$(json_str "$SUDO_MODE") ;; esac
  local data
  data=$(jobj os "$(json_str "$os_name")" osVersion "$(json_or_null "$os_version")" arch "$(json_str "$arch")" \
    shell '"bash"' shellVersion "$(json_str "$shell_version")" admin "$admin" sudo "$sudo_json" \
    packageManager "$(json_or_null "$PKG")" diskFreeGB "${free:-null}" proxy "$proxy" tools "$tools" \
    network "$net" tls "$(json_str "$TLS")")
  result checked "${os_name} ${os_version} ${arch}, bash ${shell_version}, TLS: ${TLS}" "$data"
}

# --- git -------------------------------------------------------------------------

install_package_step() {
  # install_package_step STEP TOOL PACKAGE
  local step=$1 tool=$2 package=$3 version
  version=$(tool_version "$tool")
  if [ -n "$version" ]; then
    result already "$tool $version ja estava instalado" "$(jobj version "$(json_str "$version")")"
    return
  fi
  case "$MODE" in
    check) result missing "$tool nao instalado"; return ;;
    plan) result would_install "instalaria $package pelo gerenciador de pacotes" "$(jobj command "$(json_str "$(pkg_command "$package")")")"; return ;;
  esac
  if [ -z "$PKG" ]; then
    request_action "$step" package-manager-missing external "Gerenciador de pacotes ausente. No macOS, instale e configure Homebrew seguindo https://brew.sh; no Linux use apt/dnf. Alternativamente, instale $tool pelo fornecedor e rode o instalador de novo." "" "https://brew.sh"
    result action_required "gerenciador de pacotes ausente"
    return
  fi
  if [ "$PKG" = "brew" ]; then
    if [ "$UID_NOW" -eq 0 ]; then
      request_action "$step" standard-user-required external "Homebrew nao deve rodar como root. Use a conta comum de instalacao e rode novamente."
      result action_required "Homebrew exige usuario comum"; return
    fi
  else can_be_root || { need_privilege "$step"; return; }; fi
  emit progress "$step" "" "Instalando $package" "{}"
  pkg_install "$package"
  hash -r
  version=$(tool_version "$tool")
  if [ $TOOL_CODE -ne 0 ] || [ -z "$version" ]; then
    result failed "a instalacao de $package falhou (codigo $TOOL_CODE)" "$(jobj output "$(json_str "$(limit_output "$TOOL_OUT")")")"
    return
  fi
  result installed "$tool $version instalado" "$(jobj version "$(json_str "$version")")"
}

step_git() { install_package_step git git git; }

step_git_identity() {
  local name email new_name new_email problem=""
  name=$(git config --global --get user.name 2>/dev/null)
  email=$(git config --global --get user.email 2>/dev/null)
  if [ -n "$name" ] && [ -n "$email" ]; then
    result already "identidade do git ja configurada"
    return
  fi
  case "$MODE" in
    check) result missing "user.name ou user.email vazio"; return ;;
    plan) result would_configure "pediria user.name e user.email (so os vazios)"; return ;;
  esac
  new_name=${name:-$ANSWER_GIT_NAME}
  new_email=${email:-$ANSWER_GIT_EMAIL}
  if [ -z "$new_name" ] && [ "$INTERACTIVE" -eq 1 ]; then printf 'Nome para os commits (git user.name): ' >&2; read -r new_name; fi
  if [ -z "$new_email" ] && [ "$INTERACTIVE" -eq 1 ]; then printf 'E-mail para os commits (git user.email): ' >&2; read -r new_email; fi
  if [ -z "$new_name" ] || [ -z "$new_email" ]; then
    problem="Informe o nome e o e-mail que vao assinar os commits."
  elif ! printf '%s' "$new_email" | grep -Eq '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'; then
    problem="E-mail invalido. Informe de novo."
  fi
  if [ -n "$problem" ]; then
    local items=""
    [ -n "$name" ] || items="$(answer_item git.name string Nome)"
    [ -n "$email" ] || items="${items:+${items},}$(answer_item git.email email E-mail)"
    request_action git-identity git-identity input "$problem" "" "" "[${items}]"
    result action_required "identidade do git pendente"
    return
  fi
  if [ -z "$name" ]; then
    git config --global user.name "$new_name" && [ "$(git config --global --get user.name)" = "$new_name" ] \
      || { result failed "nao foi possivel gravar user.name no git"; return; }
  fi
  if [ -z "$email" ]; then
    git config --global user.email "$new_email" && [ "$(git config --global --get user.email)" = "$new_email" ] \
      || { result failed "nao foi possivel gravar user.email no git"; return; }
  fi
  result configured "identidade do git configurada"
}

# --- gh --------------------------------------------------------------------------

# Official instructions: https://github.com/cli/cli/blob/trunk/docs/install_linux.md
install_gh_apt_repository() {
  local keyring="${SYSROOT}/etc/apt/keyrings/githubcli-archive-keyring.gpg"
  local list="${SYSROOT}/etc/apt/sources.list.d/github-cli.list"
  local work file expected created_key=false created_list=false receipt
  work=$(mktemp -d) || return 1
  download https://cli.github.com/packages/githubcli-archive-keyring.gpg "$work/key" || { rm -rf -- "$work"; return 1; }
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main\n' \
    "$(dpkg --print-architecture)" >"$work/list"
  # Never replace existing files, even files a previous run created. Key rotation
  # or administrator customizations require explicit manual reconciliation.
  for file in "$keyring" "$list"; do
    expected="$work/key"; [ "$file" != "$list" ] || expected="$work/list"
    if [ -L "$file" ] || { [ -e "$file" ] && { [ ! -f "$file" ] || ! cmp -s -- "$expected" "$file"; }; }; then
      rm -rf -- "$work"
      request_action gh gh-apt-conflict external "Configuracao APT existente divergente ou redirecionada em $file. Nada foi substituido. Preserve-a e reconcilie manualmente com o repositorio oficial do GitHub CLI."
      return 3
    fi
  done
  as_root mkdir -p -m 755 "$(dirname -- "$keyring")" "$(dirname -- "$list")" || { rm -rf -- "$work"; return 1; }
  for file in "$keyring" "$list"; do
    [ ! -e "$file" ] || continue
    expected="$work/key"; [ "$file" != "$list" ] || expected="$work/list"
    # noclobber also protects against a file appearing after the checks above.
    as_root sh -c 'umask 022; set -C; cat -- "$1" >"$2"' sh "$expected" "$file" || { rm -rf -- "$work"; return 1; }
    if [ "$file" = "$keyring" ]; then created_key=true; else created_list=true; fi
  done
  if [ "$created_key" = true ] || [ "$created_list" = true ]; then
    receipt="$CONFIG_DIR/.hubicg-station-apt-$RUN_ID.json"
    mkdir -p -- "$CONFIG_DIR" || { rm -rf -- "$work"; return 1; }
    (umask 077; set -C; jobj schema '"hubicg.station.apt/1"' keyring "$(json_str "$keyring")" keyringCreated "$created_key" keyringSha256 "$(json_str "$(sha256_of "$work/key")")" list "$(json_str "$list")" listCreated "$created_list" listSha256 "$(json_str "$(sha256_of "$work/list")")" >"$receipt") || { rm -rf -- "$work"; return 1; }
  fi
  rm -rf -- "$work"
  APT_UPDATED=0
}

ensure_curl() {
  has curl && return 0
  [ "$MODE" = "apply" ] || return 0
  can_be_root || return 1
  pkg_install curl ca-certificates
  hash -r
  has curl
}

step_gh() {
  local version
  version=$(tool_version gh)
  if [ -n "$version" ]; then
    result already "gh $version ja estava instalado" "$(jobj version "$(json_str "$version")")"
    return
  fi
  if [ "$PKG" = "apt" ]; then
    case "$MODE" in
      check) result missing "gh nao instalado"; return ;;
      plan) result would_install "configuraria o repositorio apt oficial do GitHub CLI e instalaria gh" "$(jobj command "$(json_str "$(pkg_command gh)")")"; return ;;
    esac
    can_be_root || { need_privilege gh; return; }
    ensure_curl || { result failed "curl ausente e nao foi possivel instala-lo"; return; }
    emit progress gh "" "Configurando o repositorio oficial do GitHub CLI" "{}"
    install_gh_apt_repository
    local apt_code=$?
    if [ "$apt_code" -eq 3 ]; then result action_required "configuracao APT existente preservada; reconciliacao pendente"; return; fi
    if [ "$apt_code" -ne 0 ]; then result failed "nao foi possivel configurar o repositorio apt do GitHub CLI" "$(jobj output "$(json_str "$(limit_output "$TOOL_OUT")")")"; return; fi
  fi
  install_package_step gh gh gh
}

gh_logged_in() { gh auth status --hostname github.com >/dev/null 2>&1; }

gh_device_login() {
  # Runs the official browser flow without a terminal. gh prints the one-time
  # code and the URL; both go to the interface as a browser_code action while
  # the engine waits. Without a terminal gh does not wait for Enter.
  local timeout_s=900 code="" url="https://github.com/login/device" announced=0 line
  local work login_pid started=$SECONDS login_code=0 timed_out=0
  if [ "${HUBICG_STATION_TEST_ISOLATED:-}" = 1 ]; then
    case "${HUBICG_STATION_TEST_GH_TIMEOUT:-}" in ''|*[!0-9]*|0) ;; *) timeout_s=$HUBICG_STATION_TEST_GH_TIMEOUT ;; esac
  fi
  work=$(mktemp -d) || return 1
  mkfifo "$work/output" || { rm -rf -- "$work"; return 1; }
  # A FIFO keeps device codes in memory. Keep its reader open and follow the
  # actual child PID: EOF on the child's output is not process completion.
  exec 3<>"$work/output"
  gh auth login --hostname github.com --git-protocol https --web </dev/null >"$work/output" 2>&1 3>&- &
  login_pid=$!
  trap 'kill -KILL "$login_pid" 2>/dev/null; wait "$login_pid" 2>/dev/null; exec 3>&-; rm -rf -- "$work"; exit 130' INT TERM HUP
  while true; do
    if [ $((SECONDS - started)) -ge "$timeout_s" ]; then
      timed_out=1
      kill -KILL "$login_pid" 2>/dev/null
      break
    fi
    if ! IFS= read -r -t 1 line <&3; then
      kill -0 "$login_pid" 2>/dev/null && continue
      break
    fi
    case "$line" in
      *"one-time code:"*) code=$(printf '%s' "$line" | grep -Eo '[A-Z0-9]{4}-[A-Z0-9]{4}' | head -n 1) ;;
    esac
    case "$line" in
      *"https://"*"/login/device"*) url=$(printf '%s' "$line" | grep -Eo 'https://[^[:space:]]+/login/device[^[:space:]]*' | head -n 1) ;;
    esac
    if [ -n "$code" ] && [ $announced -eq 0 ]; then
      case "$line" in
        *"/login/device"*|*"Open this URL"*|*"browser"*)
          emit action_required gh-auth action_required "Abra $url e digite o codigo $code." \
            "$(jobj id '"gh-login"' kind '"browser_code"' blocking true url "$(json_str "$url")" code "$(json_str "$code")" timeoutSeconds "$timeout_s" browserOpenedByTool false)" "$code"
          announced=1
          ;;
      esac
    fi
  done
  wait "$login_pid" 2>/dev/null || login_code=$?
  exec 3>&-
  rm -rf -- "$work"
  trap - INT TERM HUP
  if [ "$timed_out" -eq 1 ]; then
    emit action_resolved gh-auth timeout "O codigo expirou sem login; processo encerrado." '{"id":"gh-login"}'
    return 1
  fi
  if [ "$login_code" -eq 0 ] && gh_logged_in; then
    [ $announced -eq 0 ] || emit action_resolved gh-auth completed "Login no GitHub concluido." '{"id":"gh-login"}'
    return 0
  fi
  [ $announced -eq 0 ] || emit action_resolved gh-auth failed "O login no GitHub nao foi concluido (ou o codigo expirou)." '{"id":"gh-login"}'
  return 1
}

step_gh_auth() {
  local changed=""
  if ! gh_logged_in; then
    case "$MODE" in
      check) result missing "gh sem sessao valida em github.com"; return ;;
      plan) result would_configure "conduziria o login oficial do gh pelo navegador e o gh auth setup-git"; return ;;
    esac
    if [ "$INTERACTIVE" -eq 1 ]; then
      log_msg gh-auth info "Abrindo o login oficial do gh. Siga as instrucoes; o instalador nao ve o token."
      gh auth login --hostname github.com --git-protocol https --web
    else
      gh_device_login || { result failed "o login do gh nao foi concluido; rode o instalador de novo para recomecar"; return; }
    fi
    gh_logged_in || { result failed "o login do gh nao foi concluido; rode o instalador de novo para recomecar"; return; }
    changed="login"
  fi

  if has git; then
    if ! git config --global --get-all credential.https://github.com.helper 2>/dev/null | grep -q 'auth git-credential'; then
      case "$MODE" in
        check) result missing "o git ainda nao usa a credencial do gh (gh auth setup-git)"; return ;;
        plan) result would_configure "rodaria gh auth setup-git" '{"command":"gh auth setup-git --hostname github.com"}'; return ;;
      esac
      run_tool gh auth setup-git --hostname github.com
      [ $TOOL_CODE -eq 0 ] || { result failed "gh auth setup-git falhou" "$(jobj output "$(json_str "$(limit_output "$TOOL_OUT")")")"; return; }
      changed="${changed:+${changed}, }setup-git"
    fi
  fi

  if ! gh repo view "$REPOSITORY" --json name >/dev/null 2>&1; then
    if [ "$MODE" != "apply" ]; then result missing "sem acesso a $REPOSITORY"; return; fi
    request_action gh-auth repo-access external \
      "A sua conta do GitHub nao tem acesso a $REPOSITORY. Peca a um owner da organizacao HUBTECH-DEV que adicione a sua conta a um time com leitura no repositorio; depois, rode o instalador de novo." \
      "" "https://github.com/$REPOSITORY"
    result action_required "sem acesso a $REPOSITORY"
    return
  fi
  if [ -n "$changed" ]; then
    result configured "gh: ${changed}; acesso a $REPOSITORY confirmado"
  else
    result already "sessao do gh valida e acesso a $REPOSITORY confirmado"
  fi
}

# --- repo ------------------------------------------------------------------------

same_repository() {
  local normalized
  normalized=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -e 's/\.git$//' -e 's#^git@github\.com:#https://github.com/#')
  [ "$normalized" = "https://github.com/$(printf '%s' "$REPOSITORY" | tr '[:upper:]' '[:lower:]')" ]
}

step_repo() {
  local path_json
  path_json=$(json_str "$REPO_DIR")
  if [ ! -e "$REPO_DIR" ]; then
    case "$MODE" in
      check) result missing "clone ausente em $REPO_DIR"; return ;;
      plan) result would_install "clonaria $REPOSITORY em $REPO_DIR" "$(jobj command "$(json_str "git clone $REPO_URL $REPO_DIR")")"; return ;;
    esac
    mkdir -p -- "$(dirname -- "$REPO_DIR")"
    emit progress repo "" "Clonando $REPOSITORY" "{}"
    run_tool git clone "$REPO_URL" "$REPO_DIR"
    [ $TOOL_CODE -eq 0 ] || { result failed "git clone falhou" "$(jobj output "$(json_str "$(limit_output "$TOOL_OUT")")")"; return; }
    result installed "clonado em $REPO_DIR" "$(jobj path "$path_json")"
    return
  fi
  if [ ! -e "$REPO_DIR/.git" ]; then result failed "$REPO_DIR existe e nao e um clone git; nada foi alterado"; return; fi
  local origin
  origin=$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null)
  same_repository "$origin" || { result failed "$REPO_DIR aponta para outro remoto ($(protect_text "$origin")); nada foi alterado"; return; }
  case "$MODE" in
    check) result already "clone presente em $REPO_DIR" "$(jobj path "$path_json")"; return ;;
    plan) result would_update "faria fetch e pull --ff-only em $REPO_DIR" "$(jobj path "$path_json" command '"git pull --ff-only"')"; return ;;
  esac
  if [ -n "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null)" ]; then
    log_msg repo warn "O clone tem alteracoes locais. O pull nao foi feito, para nao descartar nada."
    result already "clone presente com alteracoes locais preservadas; atualizacao pulada" "$(jobj path "$path_json" dirty true)"
    return
  fi
  local before after
  before=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null)
  run_tool git -C "$REPO_DIR" fetch --prune origin
  [ $TOOL_CODE -eq 0 ] || { result failed "git fetch falhou" "$(jobj output "$(json_str "$(limit_output "$TOOL_OUT")")")"; return; }
  run_tool git -C "$REPO_DIR" pull --ff-only
  if [ $TOOL_CODE -ne 0 ]; then
    log_msg repo warn "O pull --ff-only nao foi possivel (branch divergente ou sem upstream). Nada foi descartado; resolva manualmente." "$(jobj output "$(json_str "$(limit_output "$TOOL_OUT")")")"
    result already "clone presente; avanco rapido impossivel, mantido como estava" "$(jobj path "$path_json")"
    return
  fi
  after=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null)
  if [ "$before" = "$after" ]; then
    result already "clone ja estava atualizado em $REPO_DIR" "$(jobj path "$path_json" head "$(json_str "$after")")"
  else
    result updated "clone atualizado em $REPO_DIR" "$(jobj path "$path_json" head "$(json_str "$after")")"
  fi
}

# --- claude-cli ------------------------------------------------------------------

# Official native installer: https://code.claude.com/docs/en/setup
CLAUDE_INSTALL_URL="https://claude.ai/install.sh"
CLAUDE_BIN_DIR="${HOME}/.local/bin"
PATH_MARKER="# hubicg-station: Claude Code CLI"

shell_rc() {
  case "${SHELL:-}" in
    */zsh) printf '%s' "${HOME}/.zshrc" ;;
    */bash) if [ "$OS_NAME" = "Darwin" ]; then printf '%s' "${HOME}/.bash_profile"; else printf '%s' "${HOME}/.bashrc"; fi ;;
    *) printf '%s' "${HOME}/.profile" ;;
  esac
}

step_claude_cli() {
  local version status="already"
  version=$(tool_version claude)
  if [ -z "$version" ] && [ -x "$CLAUDE_BIN_DIR/claude" ]; then
    PATH="$CLAUDE_BIN_DIR:$PATH"; hash -r; version=$(tool_version claude)
  fi
  if [ -z "$version" ]; then
    case "$MODE" in
      check) result missing "Claude Code CLI nao instalado"; return ;;
      plan) result would_install "baixaria e rodaria o instalador oficial ($CLAUDE_INSTALL_URL)" "$(jobj command "$(json_str "curl -fsSL $CLAUDE_INSTALL_URL | bash")")"; return ;;
    esac
    ensure_curl || { result failed "curl ausente e nao foi possivel instala-lo"; return; }
    emit progress claude-cli "" "Baixando o instalador oficial do Claude Code" "{}"
    local dir
    dir=$(mktemp -d) || { result failed "nao foi possivel criar diretorio temporario"; return; }
    if ! download "$CLAUDE_INSTALL_URL" "$dir/install.sh"; then
      rm -rf -- "$dir"
      result failed "o download do instalador do Claude Code falhou (codigo $TOOL_CODE)" "$(jobj output "$(json_str "$(limit_output "$TOOL_OUT")")")"
      return
    fi
    run_tool bash "$dir/install.sh"
    rm -rf -- "$dir"
    PATH="$CLAUDE_BIN_DIR:$PATH"; hash -r
    version=$(tool_version claude)
    [ -n "$version" ] || { result failed "o instalador oficial terminou, mas o comando claude nao foi encontrado" "$(jobj output "$(json_str "$(limit_output "$TOOL_OUT")")")"; return; }
    status="installed"
  fi

  local message path
  path=$(command -v claude)
  message="Claude Code $version"
  if [ "$status" = "already" ]; then message="$message ja estava instalado"; else message="$message instalado"; fi
  local rc
  rc=$(shell_rc)
  case ":${ORIGINAL_PATH}:" in
    *":${CLAUDE_BIN_DIR}:"*) ;;
    *)
      if [ "$(dirname -- "$path")" = "$CLAUDE_BIN_DIR" ] && ! grep -qF "$PATH_MARKER" "$rc" 2>/dev/null; then
        case "$MODE" in
          check) result missing "$CLAUDE_BIN_DIR nao esta no PATH" "$(jobj version "$(json_str "$version")")"; return ;;
          plan) result would_configure "incluiria $CLAUDE_BIN_DIR no PATH em $rc" "$(jobj version "$(json_str "$version")")"; return ;;
        esac
        local accepted="$ANSWER_ADD_PATH"
        if [ -z "$accepted" ] && read_yes_no "Incluir $CLAUDE_BIN_DIR no PATH (em $rc)?"; then accepted="true"; fi
        if [ "$accepted" != "true" ]; then
          request_action claude-cli claude-path confirm "O comando claude esta em $CLAUDE_BIN_DIR, que nao esta no PATH. Autoriza incluir uma linha em $rc?" \
            "printf '\\n%s\\nexport PATH=\"\$HOME/.local/bin:\$PATH\"\\n' '$PATH_MARKER' >> $rc" "" "[$(answer_item claude.addToPath boolean "Incluir ~/.local/bin no PATH")]"
          result action_required "inclusao de $CLAUDE_BIN_DIR no PATH pendente"
          return
        fi
        if ! printf '\n%s\nexport PATH="$HOME/.local/bin:$PATH"\n' "$PATH_MARKER" >>"$rc" || ! grep -qF "$PATH_MARKER" "$rc"; then
          result failed "nao foi possivel persistir o PATH em $rc"
          return
        fi
        message="$message; $CLAUDE_BIN_DIR incluido no PATH em $rc (vale para novos terminais)"
        [ "$status" != "already" ] || status="configured"
      fi
      ;;
  esac
  [ -z "${CLAUDE_CONFIG_DIR:-}" ] || message="$message; CLAUDE_CONFIG_DIR respeitado ($CLAUDE_CONFIG_DIR)"
  local node_ca=false
  if [ "$TLS" = "inspected" ] || [ "$TLS" = "suspected" ]; then
    if [ -n "${NODE_EXTRA_CA_CERTS:-}" ] && [ -r "${NODE_EXTRA_CA_CERTS}" ]; then
      node_ca=true
    else
      log_msg claude-cli warn "Inspecao TLS detectada. O Claude Code nativo confia no repositorio de CAs do sistema; se a CA corporativa nao estiver nele, defina NODE_EXTRA_CA_CERTS com o caminho do PEM da CA. Nunca desligue a verificacao TLS."
    fi
  fi
  result "$status" "$message" "$(jobj version "$(json_str "$version")" path "$(json_str "$path")" configDir "$(json_str "$CONFIG_DIR")" nodeExtraCaCerts "$node_ca")"
}

CLAUDE_AUTH_STATE=""
CLAUDE_AUTH_METHOD=""
CLAUDE_AUTH_DIR=""
CLAUDE_AUTH_DETAIL=""
claude_auth_probe() {
  # Sets CLAUDE_AUTH_STATE to logged_in, logged_out or unknown. Only a JSON
  # answer counts as "logged out": an old CLI without "auth status", a timeout
  # or an error must never be mistaken for a missing login and open the flow.
  local out code
  if has timeout; then
    out=$(timeout 30 claude auth status </dev/null 2>/dev/null)
  elif [ "$OS_NAME" = "Darwin" ]; then
    out=$(bounded_mac_auth_probe)
  else
    CLAUDE_AUTH_STATE="unknown"; CLAUDE_AUTH_METHOD=""; CLAUDE_AUTH_DIR=""
    CLAUDE_AUTH_DETAIL="timeout indisponivel; confira claude auth status num terminal"; return
  fi
  code=$?
  CLAUDE_AUTH_METHOD=""; CLAUDE_AUTH_DIR=""; CLAUDE_AUTH_DETAIL=""
  if [ $code -eq 124 ]; then
    CLAUDE_AUTH_STATE="unknown"; CLAUDE_AUTH_DETAIL="claude auth status nao respondeu em 30 s"; return
  fi
  # Validate the whole response and require a root boolean before interpreting it.
  # auth mode also strips account-identifying fields from this in-memory value.
  if ! out=$(printf '%s' "$out" | LC_ALL=C awk -v mode=auth -f "$JSON_READER"); then
    CLAUDE_AUTH_STATE="unknown"; CLAUDE_AUTH_DETAIL="claude auth status respondeu sem o JSON esperado (codigo $code)"; return
  fi
  # Only non-identifying fields are read: no e-mail, no organization.
  CLAUDE_AUTH_METHOD=$(printf '%s' "$out" | sed -n -E 's/.*"authMethod"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/p' | head -n 1)
  CLAUDE_AUTH_DIR=$(printf '%s' "$out" | sed -n -E 's/.*"configDirectory"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/p' | head -n 1)
  if [ $code -eq 0 ] && printf '%s' "$out" | grep -Eq '"loggedIn"[[:space:]]*:[[:space:]]*true'; then
    CLAUDE_AUTH_STATE="logged_in"
  elif printf '%s' "$out" | grep -Eq '"loggedIn"[[:space:]]*:[[:space:]]*false'; then
    CLAUDE_AUTH_STATE="logged_out"
  else
    CLAUDE_AUTH_STATE="unknown"; CLAUDE_AUTH_DETAIL="claude auth status retornou erro (codigo $code)"
  fi
}

step_claude_cli_auth() {
  local status="already"
  claude_auth_probe
  if [ "$CLAUDE_AUTH_STATE" = "unknown" ]; then
    case "$MODE" in
      check) result missing "sessao do Claude Code nao verificada: $CLAUDE_AUTH_DETAIL"; return ;;
      plan) result would_configure "conferiria a sessao do Claude Code ($CLAUDE_AUTH_DETAIL)"; return ;;
    esac
    request_action claude-cli-auth claude-auth-unverified run_in_terminal \
      "Nao foi possivel confirmar a sessao do Claude Code ($CLAUDE_AUTH_DETAIL). Num terminal, rode \"claude auth status\"; se o comando nao existir, atualize com \"claude update\". Se nao houver login, rode \"claude auth login\". Depois, rode o instalador de novo." \
      "claude auth status"
    result action_required "sessao do Claude Code nao verificada"
    return
  fi
  if [ "$CLAUDE_AUTH_STATE" = "logged_out" ]; then
    case "$MODE" in
      check) result missing "Claude Code CLI sem login"; return ;;
      plan) result would_configure "conduziria o login oficial (claude auth login)" '{"command":"claude auth login"}'; return ;;
    esac
    if ! read_yes_no "O Claude Code esta sem login. Abrir agora o login oficial (claude auth login)? Ele espera voce concluir no navegador."; then
      request_action claude-cli-auth claude-login run_in_terminal \
        "Faca login no Claude Code pelo fluxo oficial, num terminal: rode \"claude auth login\" e siga o navegador. Depois, rode o instalador de novo para conferir." \
        "claude auth login"
      result action_required "login do Claude Code pendente"
      return
    fi
    claude auth login
    claude_auth_probe
    [ "$CLAUDE_AUTH_STATE" = "logged_in" ] || { result failed "o login do Claude Code nao foi concluido"; return; }
    status="configured"
  fi
  if [ -n "$CLAUDE_AUTH_DIR" ] && [ "${CLAUDE_AUTH_DIR%/}" != "${CONFIG_DIR%/}" ]; then
    log_msg claude-cli-auth warn "O Claude Code usa $CLAUDE_AUTH_DIR, mas os agentes vao para $CONFIG_DIR. Confira CLAUDE_CONFIG_DIR."
  fi
  local text="sessao do Claude Code ja estava valida"
  [ "$status" = "already" ] || text="login do Claude Code concluido"
  result "$status" "$text (${CLAUDE_AUTH_METHOD:-desconhecido})" "$(jobj authMethod "$(json_or_null "$CLAUDE_AUTH_METHOD")" configDirectory "$(json_or_null "$CLAUDE_AUTH_DIR")")"
}

# --- claude-desktop ----------------------------------------------------------------

step_claude_desktop() {
  if [ "$OS_NAME" != "Darwin" ]; then result unsupported "o instalador nao instala o Claude Desktop no Linux"; return; fi
  if mac_desktop_present; then result already "Claude Desktop ja estava instalado"; return; fi
  case "$MODE" in
    check) result missing "Claude Desktop nao instalado"; return ;;
    plan) result would_install "instalaria o cask claude em ~/Applications" "$(jobj command '"brew install --cask --appdir=~/Applications claude"')"; return ;;
  esac
  if [ "$PKG" != "brew" ]; then
    request_action claude-desktop package-manager-missing external "Instale o Claude Desktop pelo fornecedor ou configure Homebrew seguindo https://brew.sh e rode novamente." "" "https://claude.com/download"
    result action_required "Homebrew ausente para instalar o Desktop"; return
  fi
  if [ "$UID_NOW" -eq 0 ]; then
    request_action claude-desktop standard-user-required external "Use uma conta comum para instalar o Claude Desktop com Homebrew."
    result action_required "Homebrew exige usuario comum"; return
  fi
  mkdir -p "$HOME/Applications" || { result failed "nao foi possivel criar ~/Applications"; return; }
  run_tool env HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ANALYTICS=1 brew install --cask "--appdir=$HOME/Applications" claude
  if [ "$TOOL_CODE" -ne 0 ] || ! mac_desktop_present; then
    result failed "a instalacao do Claude Desktop falhou" "$(jobj output "$(json_str "$(limit_output "$TOOL_OUT")")")"; return
  fi
  result installed "Claude Desktop instalado em ~/Applications"
}

mac_desktop_present() {
  case "${HUBICG_STATION_TEST_DESKTOP:-}" in installed) return 0 ;; absent) return 1 ;; esac
  [ -d "$HOME/Applications/Claude.app" ] || [ -d "${SYSROOT}/Applications/Claude.app" ]
}

step_claude_desktop_auth() {
  if [ "$OS_NAME" != "Darwin" ]; then result unsupported "sem Claude Desktop no Linux, nao ha login a confirmar"; return; fi
  local confirmed work
  confirmed=$(state_get_desktop)
  if [ -n "$confirmed" ]; then result already "login no Claude Desktop ja confirmado pelo usuario"; return; fi
  case "$MODE" in
    check) result missing "login no Claude Desktop ainda nao confirmado"; return ;;
    plan) result would_configure "abriria o Claude Desktop para o usuario confirmar o login"; return ;;
  esac
  confirmed="$ANSWER_DESKTOP"
  if [ "$confirmed" != "true" ] && [ "$INTERACTIVE" -eq 1 ]; then
    local app="${SYSROOT}/Applications/Claude.app"
    [ ! -d "$HOME/Applications/Claude.app" ] || app="$HOME/Applications/Claude.app"
    open -a "$app" >/dev/null 2>&1
    if read_yes_no "Concluiu o login no Claude Desktop?"; then confirmed=true; fi
  fi
  if [ "$confirmed" != "true" ]; then
    request_action claude-desktop-auth desktop-login-confirm confirm "Abra o Claude Desktop, faca o login e confirme. O motor nao consulta a sessao do app." "" "" "[$(answer_item desktop.loginConfirmed boolean 'Conclui o login no Claude Desktop')]"
    result action_required "confirmacao do login no Claude Desktop pendente"; return
  fi
  work=$(mktemp -d "${TMPDIR:-/tmp}/hubicg-desktop.XXXXXX") || { result failed "nao foi possivel criar diretorio temporario"; return; }
  current_state_lines "$work/agents"
  if ! write_state "$work/agents" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"; then
    rm -rf -- "$work"; result failed "nao foi possivel registrar a confirmacao do Desktop"; return
  fi
  rm -rf -- "$work"
  result configured "login no Claude Desktop confirmado pelo usuario"
}

# --- agents ------------------------------------------------------------------------

sha256_of() {
  if has sha256sum; then sha256sum -- "$1" | awk '{print $1}'; else shasum -a 256 -- "$1" | awk '{print $1}'; fi
}

managed_agent_ok() {
  # Same rule as verify_claude_agent in scripts/build_station_agents.py: the body after
  # the frontmatter must hash to the value its header declares.
  local file=$1 declared actual
  [ "$(head -n 1 -- "$file")" = "---" ] || return 1
  declared=$(awk 'NR>1 && /^---$/ {exit} /^# hubicg:managed role=[a-z0-9-]+ version=[^ ]+ hash=sha256:[0-9a-f]{64}$/ {sub(/.*hash=sha256:/, ""); print}' "$file")
  [ -n "$declared" ] || return 1
  actual=$(awk 'found==2 {print; next} /^---$/ {found++; if (found==2) {getline; next}}' "$file" | {
    if has sha256sum; then sha256sum; else shasum -a 256; fi
  } | awk '{print $1}')
  [ "$declared" = "$actual" ]
}

state_get_agent() {
  [ -f "$STATE_FILE" ] || return 0
  sed -n -E "s/^[[:space:]]*\"$(printf '%s' "$1" | sed 's/\./\\./g')\"[[:space:]]*:[[:space:]]*\"([0-9a-f]{64})\".*/\1/p" "$STATE_FILE" | head -n 1
}

state_get_desktop() {
  [ -f "$STATE_FILE" ] || return 0
  sed -n -E 's/.*"desktopLoginConfirmedAt"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/p' "$STATE_FILE" | head -n 1
}

state_agent_names() {
  [ -f "$STATE_FILE" ] || return 0
  sed -n -E 's/^[[:space:]]*"([^"]+\.md)"[[:space:]]*:.*/\1/p' "$STATE_FILE"
}

write_state() {
  # write_state AGENTS_LINES_FILE DESKTOP_CONFIRMED_AT; lines are "name hash".
  local entries="" first=1 name hash text desktop
  while read -r name hash; do
    [ -n "$name" ] || continue
    [ $first -eq 1 ] || entries="${entries},"
    entries="${entries}
    $(json_str "$name"): $(json_str "$hash")"
    first=0
  done < <(sort -u -- "$1")
  desktop=$(json_or_null "$2")
  if [ -n "$entries" ]; then entries="{${entries}
  }"; else entries="{}"; fi
  text="{
  \"schemaVersion\": \"1.0\",
  \"desktopLoginConfirmedAt\": ${desktop},
  \"agents\": ${entries}
}"
  # Unchanged state is not rewritten: a second run must not touch the disk.
  if [ -f "$STATE_FILE" ] && [ "$(cat -- "$STATE_FILE")" = "$text" ]; then return 0; fi
  mkdir -p -- "$CONFIG_DIR" || return 1
  if printf '%s\n' "$text" >"$STATE_FILE.tmp.$$" && mv -f -- "$STATE_FILE.tmp.$$" "$STATE_FILE"; then
    return 0
  fi
  rm -f -- "$STATE_FILE.tmp.$$"
  return 1
}

current_state_lines() {
  local out=$1 name
  : >"$out"
  for name in $(state_agent_names); do
    printf '%s %s\n' "$name" "$(state_get_agent "$name")" >>"$out"
  done
}

step_agents() {
  if [ ! -d "$AGENTS_SOURCE" ]; then
    case "$MODE" in
      check) result missing "os agentes serao instalados de $AGENTS_SOURCE depois do clone" ;;
      plan) result would_install "os agentes serao instalados de $AGENTS_SOURCE depois do clone" ;;
      *) request_action agents agents-export external "Gere os agentes publicos: python3 scripts/build_station_agents.py (no clone $REPO_DIR); ou informe --agents-source com um export validado."
         result action_required "export publico de agentes ausente: $AGENTS_SOURCE" ;;
    esac
    return
  fi
  if [ "$AGENTS_DEFAULT" -eq 1 ]; then
    local library_file="$REPO_DIR/src/hubicg/library/manifest.json"
    local receipt_file="$AGENTS_SOURCE/.hubicg-station-export.json" recorded_library="" receipt_schema=""
    if [ -f "$receipt_file" ]; then
      recorded_library=$(LC_ALL=C awk -v key=/libraryManifestSha256 -v required_type=string -f "$JSON_READER" "$receipt_file" 2>/dev/null)
      receipt_schema=$(LC_ALL=C awk -v key=/schema -v required_type=string -f "$JSON_READER" "$receipt_file" 2>/dev/null)
    fi
    if [ ! -f "$library_file" ] || [ "$receipt_schema" != "hubicg.station.agents-export/1" ] || [ "$recorded_library" != "$(sha256_of "$library_file" 2>/dev/null)" ]; then
      case "$MODE" in
        check) result missing "export ausente, sem recibo ou desatualizado para a biblioteca do clone" ;;
        plan) result would_install "geraria um export correspondente a biblioteca do clone" ;;
        *) request_action agents agents-export-stale external "O export nao corresponde a biblioteca de $REPO_DIR. Preserve a pasta antiga com outro nome e gere um export novo no caminho padrao com Python 3.11+: python3 scripts/build_station_agents.py. Artefato externo explicito usa --agents-source e origem propria."
           result action_required "export desatualizado ou sem origem verificavel no clone; nenhum agente foi alterado" ;;
      esac
      return
    fi
  fi
  local target="${CONFIG_DIR}/agents" work file name hash current recorded
  local installed=0 updated=0 already=0 removed=0 conflict=0 total=0 conflicts_json=""
  work=$(mktemp -d) || { result failed "nao foi possivel criar diretorio temporario"; return; }
  current_state_lines "$work/before"
  cp -- "$work/before" "$work/after"

  for file in "$AGENTS_SOURCE"/*.md; do
    [ -f "$file" ] || continue
    if ! managed_agent_ok "$file"; then
      rm -rf -- "$work"
      result failed "agente de origem corrompido ou editado a mao: $(basename -- "$file"). Nada foi instalado; atualize o clone."
      return
    fi
    total=$((total + 1))
  done
  [ $total -gt 0 ] || { rm -rf -- "$work"; result failed "nenhum agente em $AGENTS_SOURCE"; return; }
  if [ "$MODE" = "apply" ] && ! mkdir -p -- "$target"; then
    rm -rf -- "$work"; result failed "nao foi possivel criar $target"; return
  fi

  for file in "$AGENTS_SOURCE"/*.md; do
    name=$(basename -- "$file")
    hash=$(sha256_of "$file")
    local action="installed"
    if [ -e "$target/$name" ]; then
      current=$(sha256_of "$target/$name")
      if [ "$current" = "$hash" ]; then
        already=$((already + 1))
        if [ "$MODE" = "apply" ]; then
          grep -v "^$name " "$work/after" >"$work/tmp"; printf '%s %s\n' "$name" "$hash" >>"$work/tmp"; mv -f -- "$work/tmp" "$work/after"
        fi
        continue
      fi
      recorded=$(state_get_agent "$name")
      if [ -z "$recorded" ] || [ "$recorded" != "$current" ]; then
        # Not written by this installer, or edited after it was: never overwrite.
        conflict=$((conflict + 1))
        conflicts_json="${conflicts_json:+${conflicts_json},}$(json_str "$name")"
        continue
      fi
      action="updated"
    fi
    if [ "$MODE" = "apply" ]; then
      if ! { cp -- "$file" "$target/$name.tmp.$$" && mv -f -- "$target/$name.tmp.$$" "$target/$name"; }; then
        # Persist what did succeed, so the manifest never claims a file that is not there.
        rm -f -- "$target/$name.tmp.$$"
        write_state "$work/after" "$(state_get_desktop)"
        rm -rf -- "$work"
        result failed "nao foi possivel gravar $target/$name; os agentes ja gravados ficaram no manifesto"
        return
      fi
      grep -v "^$name " "$work/after" >"$work/tmp"; printf '%s %s\n' "$name" "$hash" >>"$work/tmp"; mv -f -- "$work/tmp" "$work/after"
    fi
    if [ "$action" = "installed" ]; then installed=$((installed + 1)); else updated=$((updated + 1)); fi
  done

  for name in $(state_agent_names); do
    [ ! -f "$AGENTS_SOURCE/$name" ] || continue
    if [ ! -e "$target/$name" ]; then
      if [ "$MODE" = "apply" ]; then grep -v "^$name " "$work/after" >"$work/tmp"; mv -f -- "$work/tmp" "$work/after"; fi
    elif [ "$(sha256_of "$target/$name")" = "$(state_get_agent "$name")" ]; then
      if [ "$MODE" = "apply" ]; then
        if ! rm -f -- "$target/$name"; then
          write_state "$work/after" "$(state_get_desktop)"
          rm -rf -- "$work"
          result failed "nao foi possivel remover $target/$name; registro mantido no manifesto"
          return
        fi
        grep -v "^$name " "$work/after" >"$work/tmp"; mv -f -- "$work/tmp" "$work/after"
      fi
      removed=$((removed + 1))
    fi
  done

  local adopted=0
  if [ "$MODE" = "apply" ]; then
    sort -u -o "$work/before" -- "$work/before"; sort -u -o "$work/after" -- "$work/after"
    cmp -s -- "$work/before" "$work/after" || adopted=1
    if ! write_state "$work/after" "$(state_get_desktop)"; then
      rm -rf -- "$work"; result failed "nao foi possivel gravar o manifesto $STATE_FILE"; return
    fi
  fi
  rm -rf -- "$work"

  for name in $(printf '%s' "$conflicts_json" | tr -d '"' | tr ',' ' '); do
    log_msg agents warn "$name ja existe em $target, nao foi instalado por este instalador (ou foi alterado depois) e foi mantido como estava."
  done
  local counts data summary
  counts=$(jobj installed "$installed" updated "$updated" already "$already" removed "$removed" conflict "$conflict")
  local source_mode=external
  [ "$AGENTS_DEFAULT" -eq 0 ] || source_mode=clone-library
  data=$(jobj target "$(json_str "$target")" source "$(json_str "$AGENTS_SOURCE")" sourceMode "$(json_str "$source_mode")" total "$total" counts "$counts" conflicts "[${conflicts_json}]")
  summary="$total agentes: $installed novos, $updated atualizados, $already iguais, $removed removidos, $conflict conflitos mantidos"
  if [ $((installed + updated + removed)) -eq 0 ]; then
    # Adopting identical files into a new manifest is still a change on disk.
    if [ $adopted -eq 1 ]; then result configured "$summary; manifesto atualizado" "$data"; else result already "$summary" "$data"; fi
    return
  fi
  case "$MODE" in
    check) result missing "$summary" "$data" ;;
    plan) result would_install "$summary" "$data" ;;
    *) if [ $installed -gt 0 ]; then result installed "$summary" "$data"; else result updated "$summary" "$data"; fi ;;
  esac
}

# --- Runner ------------------------------------------------------------------------

ORIGINAL_PATH="$PATH"
steps_json=""
for s in $ALL_STEPS; do steps_json="${steps_json:+${steps_json},}$(json_str "$s")"; done
interactive_json=false
[ "$INTERACTIVE" -eq 0 ] || interactive_json=true
case "$(uname -s)" in
  Linux) os_json='"linux"' ;;
  Darwin) os_json='"macos"' ;;
  *) os_json='"linux"' ;;
esac
emit run_start "" "" "HubICG station $ENGINE_VERSION" "$(jobj engine "$(json_str "$ENGINE_VERSION")" contract 1 mode "$(json_str "$MODE")" os "$os_json" interactive "$interactive_json" steps "[${steps_json}]" repoDir "$(json_str "$REPO_DIR")" configDir "$(json_str "$CONFIG_DIR")" logFile "$(json_str "$LOG_FILE")")"

if [ "$OS_NAME" != "Linux" ] && [ "$OS_NAME" != "Darwin" ]; then
  emit run_end "" exit_4 "Sistema sem suporte. No Windows, use hubicg-station.ps1." '{"exitCode":4,"steps":{}}'
  exit 4
fi
if [ "$OS_NAME" = "Darwin" ]; then
  mac_version=$(sw_vers -productVersion)
  case "$mac_version" in ''|*[!0-9.]*) mac_version=0 ;; esac
  case "$(uname -m)" in x86_64|arm64) ;; *) mac_version=0 ;; esac
  if [ "${mac_version%%.*}" -lt 13 ]; then
    emit run_end "" exit_4 "Claude exige macOS 13+ em Intel x86_64 ou Apple Silicon arm64." '{"exitCode":4,"steps":{}}'
    exit 4
  fi
fi

depends_on() {
  case "$1" in
    git-identity) printf 'git' ;;
    gh-auth) printf 'gh' ;;
    repo) printf 'git gh-auth' ;;
    claude-cli-auth) printf 'claude-cli' ;;
    claude-desktop-auth) printf 'claude-desktop' ;;
    agents) printf 'repo' ;;
  esac
}

var_of() { printf 'RES_%s' "$1" | tr '-' '_'; }

total_steps=0
for s in $ALL_STEPS; do total_steps=$((total_steps + 1)); done
index=0
summary_json=""
any_failed=0; any_action=0; any_pending=0
for step in $ALL_STEPS; do
  index=$((index + 1))
  emit step_start "$step" "" "" "$(jobj index "$index" total "$total_steps")"
  selected=1
  if [ -n "$ONLY" ] && [ "$step" != "environment" ]; then
    case ",$ONLY," in *",$step,"*) ;; *) selected=0 ;; esac
  fi
  if [ $selected -eq 0 ]; then
    result skipped "fora da selecao de --only"
  else
    blocked=""
    if [ "$MODE" = "apply" ]; then
      for dep in $(depends_on "$step"); do
        eval "dep_status=\${$(var_of "$dep"):-}"
        case "$dep_status" in failed|action_required|blocked) blocked="${blocked:+${blocked}, }$dep" ;; esac
      done
    fi
    if [ -n "$blocked" ]; then
      blocked_json=""
      for dep in $(printf '%s' "$blocked" | tr -d ','); do blocked_json="${blocked_json:+${blocked_json},}$(json_str "$dep")"; done
      result blocked "depende de: $blocked" "{\"blockedBy\":[${blocked_json}]}"
    else
      R_STATUS=""; R_MESSAGE=""; R_DATA="{}"
      "step_$(printf '%s' "$step" | tr '-' '_')"
      [ -n "$R_STATUS" ] || result failed "erro inesperado: a etapa nao reportou resultado"
    fi
  fi
  eval "$(var_of "$step")=\$R_STATUS"
  summary_json="${summary_json:+${summary_json},}$(json_str "$step"):$(json_str "$R_STATUS")"
  case "$R_STATUS" in
    failed) any_failed=1 ;;
    action_required|blocked) any_action=1 ;;
    missing|would_install|would_configure|would_update) any_pending=1 ;;
  esac
  emit step_end "$step" "$R_STATUS" "$R_MESSAGE" "$R_DATA"
done

exit_code=0
final="Concluido: nada pendente."
if [ $any_failed -eq 1 ]; then exit_code=1; final="Terminou com falha; veja as etapas marcadas como failed."
elif [ $any_action -eq 1 ]; then exit_code=3; final="Ha acoes suas pendentes; conclua-as e rode o instalador de novo."
elif [ $any_pending -eq 1 ]; then exit_code=5; final="Ha itens a instalar ou configurar; rode sem --check/--dry-run para aplicar."
fi
end_status="ok"
[ $exit_code -eq 0 ] || end_status="exit_${exit_code}"
emit run_end "" "$end_status" "$final" "{\"exitCode\":${exit_code},\"steps\":{${summary_json}}}"
exit $exit_code
