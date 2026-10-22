#!/bin/bash
# Adaptador de processos da GUI. Nunca instala nem interpreta a lógica do motor.
set -m
engine_pid=
interrupt() {
    trap '' INT TERM
    engine_pid=${engine_pid:-$!}
    if [ -n "$engine_pid" ]; then
        kill -TERM -- "-$engine_pid" 2>/dev/null || :
        sleep 1
        kill -KILL -- "-$engine_pid" 2>/dev/null || :
        wait "$engine_pid" 2>/dev/null || :
    fi
    exit 130
}
trap interrupt INT TERM
"$@" </dev/null &
engine_pid=$!
wait "$engine_pid"
result=$?
trap - INT TERM
exit "$result"
