import tomllib

from hubicg.adapters.codex import (
    codex_agent_name,
    content_hash,
    find_conflicts,
    find_name_collisions,
    parse_marker,
    render_custom_agent,
)

ROLE = {
    "schemaVersion": "1.0",
    "id": "principal-git-engineer",
    "name": "Principal Git Engineer",
    "instructions": "Inspect the worktree before proposing changes.",
    "version": "1.0.0",
    "locale": "en",
    "tags": ["git", "governance"],
    "capabilities": ["branch-strategy"],
}


def test_render_custom_agent_golden_and_valid_toml() -> None:
    rendered = render_custom_agent(ROLE)
    assert rendered == (
        f"# hubicg:managed adapter=codex role=principal-git-engineer version=1.0.0 hash={content_hash(ROLE)}\n"
        'name = "principal_git_engineer"\n'
        'description = "Principal Git Engineer. Use for: git, governance, branch-strategy."\n'
        'developer_instructions = "Inspect the worktree before proposing changes."\n'
    )
    assert tomllib.loads(rendered) == {
        "name": "principal_git_engineer",
        "description": "Principal Git Engineer. Use for: git, governance, branch-strategy.",
        "developer_instructions": "Inspect the worktree before proposing changes.",
    }


def test_render_escapes_quotes_backslashes_newlines_unicode_and_triple_quotes() -> None:
    role = {
        **ROLE,
        "instructions": 'Use "quotes", C:\\repo,\nUnicode: ação, and triple: """ safely.',
    }
    parsed = tomllib.loads(render_custom_agent(role))
    assert parsed["developer_instructions"] == role["instructions"]


def test_render_escapes_unescaped_del_control_character() -> None:
    role = {**ROLE, "instructions": "Before\x7fAfter"}
    parsed = tomllib.loads(render_custom_agent(role))
    assert parsed["developer_instructions"] == role["instructions"]


def test_hash_changes_for_every_rendered_role_field() -> None:
    changes = [
        {"id": "other-role"},
        {"name": "Other name"},
        {"instructions": "Other instructions"},
        {"version": "2.0.0"},
        {"tags": ["git"]},
        {"capabilities": ["code-review"]},
        {"locale": "pt-BR"},
    ]
    original = content_hash(ROLE)
    assert all(content_hash({**ROLE, **change}) != original for change in changes)


def test_marker_round_trips_and_manual_file_is_unmanaged() -> None:
    marker = parse_marker(render_custom_agent(ROLE))
    assert marker == {
        "role": ROLE["id"],
        "version": ROLE["version"],
        "hash": content_hash(ROLE).removeprefix("sha256:"),
    }
    assert parse_marker('name = "manual"\n') is None


def test_agent_name_uses_codex_underscore_convention() -> None:
    assert codex_agent_name("principal-git-engineer") == "principal_git_engineer"


def test_conflicts_and_normalized_name_collisions_are_reported() -> None:
    roles = [{**ROLE, "id": "a", "conflictsWith": ["b"]}, {**ROLE, "id": "b"}]
    assert find_conflicts(roles) == [("a", "b")]
    assert find_name_collisions([{**ROLE, "id": "a-b"}, {**ROLE, "id": "a_b"}]) == [("a-b", "a_b")]


def test_render_is_idempotent() -> None:
    assert render_custom_agent(ROLE) == render_custom_agent(dict(ROLE))
