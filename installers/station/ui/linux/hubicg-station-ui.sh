#!/bin/sh
# Ponto de entrada do assistente do instalador da estacao HubICG no Linux (interface L1).
#
#   ./hubicg-station-ui.sh                  abre o assistente (zenity; kdialog no KDE; terminal sem desktop)
#   ./hubicg-station-ui.sh --frontend terminal
#   ./hubicg-station-ui.sh --criar-atalho   cria o atalho no menu de aplicativos e na area de trabalho
#
# O assistente e Python 3 so com a biblioteca padrao, que ja vem nos desktops Linux suportados.
set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

criar_atalho() {
  apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  mkdir -p "$apps"
  entry="$apps/hubicg-station.desktop"
  # Caminho absoluto: o atalho funciona de qualquer lugar. Aspas e $ escapados pela especificacao .desktop.
  escaped=$(printf '%s' "$DIR/hubicg-station-ui.sh" | sed 's/[\\"`$]/\\\\&/g; s/%/%%/g')
  {
    printf '%s\n' '[Desktop Entry]' 'Type=Application' 'Version=1.0'
    printf '%s\n' 'Name=Instalar a estação HubICG' 'Comment=Assistente do instalador da estação HubICG'
    # Keep the executable name free of field codes; GIO expands %% in arguments.
    printf 'Exec=sh "%s"\n' "$escaped"
    printf '%s\n' 'Icon=system-software-install' 'Terminal=false' 'Categories=Development;'
  } > "$entry"
  chmod 755 "$entry"
  desktop=$(xdg-user-dir DESKTOP 2>/dev/null || printf '%s' "$HOME/Desktop")
  if [ -d "$desktop" ]; then
    cp "$entry" "$desktop/hubicg-station.desktop"
    chmod 755 "$desktop/hubicg-station.desktop"
    # GNOME (Desktop Icons NG) so executa atalhos marcados como confiaveis.
    gio set "$desktop/hubicg-station.desktop" metadata::trusted true 2>/dev/null || true
  fi
  printf 'Atalho criado: %s\n' "$entry"
}

if [ "${1:-}" = "--criar-atalho" ]; then
  criar_atalho
  exit 0
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$DIR/hubicg_station_ui.py" "$@"
fi

msg="O assistente do instalador precisa do python3, que não foi encontrado. Instale o pacote python3 (sudo apt install python3, ou sudo dnf install python3) e tente de novo."
if command -v zenity >/dev/null 2>&1; then
  zenity --error --title="Instalador da estação HubICG" --text="$msg"
elif command -v kdialog >/dev/null 2>&1; then
  kdialog --title "Instalador da estação HubICG" --error "$msg"
else
  printf '%s\n' "$msg" >&2
fi
exit 1
