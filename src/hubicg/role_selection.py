"""Deterministic, multilingual-friendly local role selection."""

from __future__ import annotations

import re
import shlex
import unicodedata
from dataclasses import dataclass
from typing import Any

FILTER_NAMES = {
    "source": "source", "fonte": "source", "origen": "source",
    "lang": "locale", "language": "locale", "idioma": "locale",
    "tag": "tag", "etiqueta": "tag",
    "cap": "capability", "capability": "capability", "capacidade": "capability",
}
SOURCE_PRIORITY = {"custom": 3, "project": 2, "official": 1}


def normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def tokens(value: str) -> list[str]:
    return re.findall(r"[^\W_]+", normalized(value), flags=re.UNICODE)


@dataclass(frozen=True)
class Query:
    terms: tuple[str, ...]
    filters: dict[str, tuple[str, ...]]


def parse_query(value: str) -> Query:
    filters: dict[str, list[str]] = {"source": [], "locale": [], "tag": [], "capability": []}
    free: list[str] = []
    try:
        parts = shlex.split(value)
    except ValueError:
        parts = value.split()
    for part in parts:
        name, separator, filter_value = part.partition(":")
        canonical = FILTER_NAMES.get(normalized(name)) if separator else None
        if canonical and filter_value:
            filters[canonical].append(normalized(filter_value))
        else:
            free.extend(tokens(part))
    return Query(tuple(free), {key: tuple(values) for key, values in filters.items() if values})


def _values(payload: dict[str, Any], field: str) -> list[str]:
    value = payload.get(field, [])
    return [normalized(str(item)) for item in value] if isinstance(value, list) else []


def _passes(payload: dict[str, Any], query: Query) -> bool:
    source = normalized(str(payload.get("_source", "project")))
    locale = normalized(str(payload.get("locale", "und")))
    if query.filters.get("source") and source not in query.filters["source"]:
        return False
    if query.filters.get("locale") and not any(locale == item or locale.startswith(item + "-") for item in query.filters["locale"]):
        return False
    if query.filters.get("tag") and not set(query.filters["tag"]).issubset(_values(payload, "tags")):
        return False
    if query.filters.get("capability") and not set(query.filters["capability"]).issubset(_values(payload, "capabilities")):
        return False
    return True


def _score(payload: dict[str, Any], query: Query) -> tuple[int, list[str]]:
    source = str(payload.get("_source", "project"))
    score = SOURCE_PRIORITY.get(source, 0)
    reasons = [f"source:{source}"]
    fields = {
        "id": normalized(str(payload.get("id", ""))),
        "name": normalized(str(payload.get("name", ""))),
        "instructions": normalized(str(payload.get("instructions", ""))),
        "tags": " ".join(_values(payload, "tags")),
        "capabilities": " ".join(_values(payload, "capabilities")),
    }
    weights = {"id": 30, "name": 20, "tags": 16, "capabilities": 14, "instructions": 4}
    matched = 0
    for term in query.terms:
        term_score = 0
        term_fields: list[str] = []
        for field, text in fields.items():
            if term in text:
                term_score += weights[field]
                term_fields.append(field)
        if term_score:
            matched += 1
            score += term_score * 100
            reasons.append(f"term:{term}@{'+'.join(term_fields)}")
    if query.terms and matched != len(query.terms):
        return 0, []
    for name, values in query.filters.items():
        reasons.extend(f"filter:{name}={value}" for value in values)
    return score, reasons


def select_roles(payloads: list[dict[str, Any]], query_text: str, count: int) -> dict[str, Any]:
    query = parse_query(query_text)
    candidates: list[tuple[int, str, dict[str, Any], list[str]]] = []
    for payload in payloads:
        if not _passes(payload, query):
            continue
        score, reasons = _score(payload, query)
        if score:
            candidates.append((score, normalized(str(payload.get("name", ""))), payload, reasons))
    candidates.sort(key=lambda item: (-item[0], item[1], str(item[2].get("id", ""))))

    selected: list[dict[str, Any]] = []
    conflicts: list[dict[str, str]] = []
    selected_payloads: list[dict[str, Any]] = []
    for score, _name, payload, reasons in candidates:
        role_id = str(payload.get("id"))
        blocked_by = None
        declared = set(str(item) for item in payload.get("conflictsWith", []))
        for chosen in selected_payloads:
            chosen_id = str(chosen.get("id"))
            reverse = set(str(item) for item in chosen.get("conflictsWith", []))
            if chosen_id in declared or role_id in reverse:
                blocked_by = chosen_id
                break
        if blocked_by:
            conflicts.append({"role": role_id, "blockedBy": blocked_by, "reason": "declared-conflict"})
            continue
        selected_payloads.append(payload)
        selected.append({
            "id": role_id,
            "name": payload.get("name"),
            "source": payload.get("_source", "project"),
            "locale": payload.get("locale", "und"),
            "version": payload.get("version", "1"),
            "contentHash": payload.get("_contentHash"),
            "score": score,
            "reasons": reasons,
        })
        if len(selected) >= count:
            break
    return {
        "query": query_text,
        "terms": list(query.terms),
        "filters": {key: list(values) for key, values in query.filters.items()},
        "selected": selected,
        "conflicts": conflicts,
        "policy": {"sourcePriority": ["custom", "project", "official"], "network": "disabled"},
    }
