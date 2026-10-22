#!/usr/bin/env python3
"""Confere um fluxo de eventos do motor contra o contrato.

Uso: ``validate_events.py EVENTOS.jsonl CODIGO_DE_SAIDA``. Usado pela CI depois
do check e do dry-run reais, onde o resultado depende do runner: o que se
confere é a forma, não o conteúdo. Check e dry-run nunca podem falhar por
estado do ambiente, então os códigos aceitos são 0, 3 e 5.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.station_fakes.schema_subset import SchemaValidationError, validate_instance

ESQUEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "docs" / "schemas" / "station-event.schema.json").read_text(encoding="utf-8")
)
TIPOS = set(ESQUEMA["properties"]["type"]["enum"])
STATUS = set(ESQUEMA["allOf"][0]["then"]["properties"]["status"]["enum"])
CODIGOS_ACEITOS = {0, 3, 5}


def validate_event(value, schema=ESQUEMA, location="$"):
    """Validate every station-schema constraint, including conditional branches.

    The bootstrap validator covers the primitive keywords; station adds allOf
    and if/then, which are evaluated here without a runtime dependency.
    """
    validate_instance(value, schema, location)
    def equal(left, right):
        return left == right and (isinstance(left, bool) == isinstance(right, bool))
    if "const" in schema and not equal(value, schema["const"]):
        raise SchemaValidationError(f"{location}: wrong constant")
    if "enum" in schema and not any(equal(value, item) for item in schema["enum"]):
        raise SchemaValidationError(f"{location}: outside enum")
    for child in schema.get("allOf", []):
        validate_event(value, child, location)
    if "if" in schema:
        try:
            validate_event(value, schema["if"], location)
        except SchemaValidationError:
            branch = "else"
        else:
            branch = "then"
        if branch in schema:
            validate_event(value, schema[branch], location)
    if isinstance(value, dict):
        for key, child in schema.get("properties", {}).items():
            if key in value:
                validate_event(value[key], child, f"{location}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            validate_event(item, schema["items"], f"{location}[{index}]")


def main() -> int:
    arquivo, codigo = Path(sys.argv[1]), int(sys.argv[2])
    linhas = [l for l in arquivo.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    eventos = [json.loads(l) for l in linhas]
    problemas = []
    if not eventos or eventos[0]["type"] != "run_start" or eventos[-1]["type"] != "run_end":
        problemas.append("o fluxo precisa começar em run_start e terminar em run_end")
    if [e["seq"] for e in eventos] != list(range(1, len(eventos) + 1)):
        problemas.append("seq não é contínuo")
    for e in eventos:
        try:
            validate_event(e)
        except SchemaValidationError as error:
            problemas.append(f"evento {e.get('seq')}: {error}")
        faltando = [c for c in ESQUEMA["required"] if c not in e]
        if faltando:
            problemas.append(f"evento {e.get('seq')} sem {faltando}")
        if e.get("type") not in TIPOS:
            problemas.append(f"tipo desconhecido: {e.get('type')}")
        if e.get("type") == "step_end" and e.get("status") not in STATUS:
            problemas.append(f"status desconhecido em {e.get('step')}: {e.get('status')}")
    if eventos and eventos[-1]["data"].get("exitCode") != codigo:
        problemas.append(f"run_end diz {eventos[-1]['data'].get('exitCode')}, o processo saiu com {codigo}")
    if codigo not in CODIGOS_ACEITOS:
        problemas.append(f"código de saída {codigo} fora de {sorted(CODIGOS_ACEITOS)}")
    for e in eventos:
        if e["type"] in ("step_end", "run_end"):
            print(f"{e['step'] or 'run'}: {e['status']} - {e['message']}")
    for p in problemas:
        print(f"ERRO: {p}", file=sys.stderr)
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
