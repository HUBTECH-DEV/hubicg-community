#!/bin/bash
# Fixture M1 sem instalação, autenticação ou leitura de configuração pessoal.
cat <<'EVENTS'
{"schema":"hubicg.station.event/1","runId":"m1-fixture","seq":1,"ts":"2026-10-22T00:00:00Z","type":"run_start","step":"","status":"","message":"Fixture macOS","data":{"engine":"fixture","contract":1,"mode":"check","os":"macos","interactive":false,"steps":["environment","gh"],"repoDir":"/tmp/hubicg-fixture","configDir":"/tmp/hubicg-fixture-config","logFile":"/tmp/hubicg-fixture-log"}}
{"schema":"hubicg.station.event/1","runId":"m1-fixture","seq":2,"ts":"2026-10-22T00:00:00Z","type":"step_start","step":"environment","status":"","message":"Verificação","data":{"index":1,"total":2}}
{"schema":"hubicg.station.event/1","runId":"m1-fixture","seq":3,"ts":"2026-10-22T00:00:00Z","type":"step_end","step":"environment","status":"checked","message":"Ambiente simulado","data":{"os":"macos","osVersion":"15.8","arch":"x86_64","shell":"bash","shellVersion":"3.2","admin":false,"sudo":"absent","packageManager":null,"diskFreeGB":10,"proxy":{},"tools":{"git":"fixture","gh":null},"network":{},"tls":"skipped"}}
{"schema":"hubicg.station.event/1","runId":"m1-fixture","seq":4,"ts":"2026-10-22T00:00:00Z","type":"step_start","step":"gh","status":"","message":"GitHub CLI","data":{"index":2,"total":2}}
{"schema":"hubicg.station.event/1","runId":"m1-fixture","seq":5,"ts":"2026-10-22T00:00:00Z","type":"step_end","step":"gh","status":"missing","message":"Pré-requisito ausente — exemplo sintético","data":{}}
{"schema":"hubicg.station.event/1","runId":"m1-fixture","seq":6,"ts":"2026-10-22T00:00:00Z","type":"run_end","step":"","status":"","message":"Fim da fixture","data":{"exitCode":5,"steps":{"environment":"checked","gh":"missing"}}}
EVENTS
exit 5
