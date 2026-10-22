#!/bin/bash
# Teste bash 3.2 nativo, sem instalação, GUI ou autenticação.
set -u
gui=$1
work=$(mktemp -d /tmp/hubicg-m1-process.XXXXXXXX) || exit 1
wrapper_pid=
cleanup() {
    if [ -n "$wrapper_pid" ] && kill -0 "$wrapper_pid" 2>/dev/null; then
        kill -TERM "$wrapper_pid" 2>/dev/null || :
        wait "$wrapper_pid" 2>/dev/null || :
    fi
    case "$work" in /tmp/hubicg-m1-process.*) rm -rf -- "$work" ;; esac
}
trap cleanup EXIT
/bin/bash "$gui/StationUi.Process.sh" /bin/bash -c 'read -r ignored && exit 9; printf "fixture\n"; exit 3' > "$work/normal"
status=$?
[ "$status" -eq 3 ] && [ "$(cat "$work/normal")" = fixture ] || exit 1
cat > "$work/engine.sh" <<'FIXTURE'
trap '' TERM
sleep 60 &
child=$!
printf '%s\n' "$child"
wait "$child"
FIXTURE
/bin/bash "$gui/StationUi.Process.sh" /bin/bash "$work/engine.sh" > "$work/pid" 2> "$work/errors" &
wrapper_pid=$!
tries=0
while [ ! -s "$work/pid" ] && [ "$tries" -lt 30 ]; do sleep 0.1; tries=$((tries + 1)); done
[ -s "$work/pid" ] || exit 1
child=$(cat "$work/pid")
kill -TERM "$wrapper_pid" || exit 1
tries=0
while kill -0 "$wrapper_pid" 2>/dev/null && [ "$tries" -lt 60 ]; do sleep 0.1; tries=$((tries + 1)); done
[ "$tries" -lt 60 ] || exit 1
wait "$wrapper_pid"
status=$?
wrapper_pid=
[ "$status" -eq 130 ] || exit 1
child_state=$(ps -p "$child" -o stat= 2>/dev/null || :)
case "$child_state" in ''|*Z*) ;; *) exit 1 ;; esac
printf 'native_process_exit_stdin_cancel=ok\n'
