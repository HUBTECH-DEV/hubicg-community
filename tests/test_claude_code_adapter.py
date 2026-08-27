from hubicg.adapters.claude_code import content_hash, parse_marker, render_subagent

ROLE = {
    "schemaVersion": "1.0",
    "id": "principal-git-engineer",
    "name": "Principal Git Engineer",
    "instructions": "Inspecionar worktree antes de propor mudanças.",
    "version": "1.0.0",
    "tags": ["git", "governance"],
    "capabilities": ["branch-strategy"],
}


def test_render_subagent_golden() -> None:
    rendered = render_subagent(ROLE)
    expected_hash = content_hash(ROLE["name"], ROLE["instructions"])
    assert rendered == (
        f"<!-- hubicg:managed role=principal-git-engineer version=1.0.0 hash={expected_hash} -->\n"
        "---\n"
        "name: principal-git-engineer\n"
        "description: git, governance, branch-strategy\n"
        "---\n"
        "\n"
        "Inspecionar worktree antes de propor mudanças.\n"
    )


def test_render_subagent_is_idempotent() -> None:
    assert render_subagent(ROLE) == render_subagent(dict(ROLE))


def test_render_subagent_hash_changes_with_instructions() -> None:
    changed = {**ROLE, "instructions": "Outra instrução."}
    assert render_subagent(ROLE) != render_subagent(changed)


def test_render_subagent_falls_back_to_id_without_tags_or_capabilities() -> None:
    minimal = {
        "schemaVersion": "1.0", "id": "bare-role", "name": "Bare Role",
        "instructions": "Fazer algo.",
    }
    rendered = render_subagent(minimal)
    assert "description: bare-role\n" in rendered


def test_parse_marker_round_trips_generated_output() -> None:
    rendered = render_subagent(ROLE)
    marker = parse_marker(rendered)
    assert marker == {
        "role": "principal-git-engineer",
        "version": "1.0.0",
        "hash": content_hash(ROLE["name"], ROLE["instructions"])[len("sha256:"):],
    }


def test_parse_marker_returns_none_for_hand_authored_file() -> None:
    assert parse_marker("---\nname: my-agent\n---\n\nHand-written.\n") is None


def test_parse_marker_returns_none_when_marker_is_not_first_line() -> None:
    text = "Some preamble\n<!-- hubicg:managed role=x version=1 hash=sha256:" + "0" * 64 + " -->\n"
    assert parse_marker(text) is None
