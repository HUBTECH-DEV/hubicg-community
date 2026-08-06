"""Command-line interface for the HubICG Community governance foundation."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXIT_INVALID, EXIT_USAGE, EXIT_APPROVAL, EXIT_EXTERNAL = 1, 2, 3, 4


class HubICGError(RuntimeError):
    def __init__(self, message: str, code: int = EXIT_INVALID):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Context:
    root: Path
    as_json: bool

    @property
    def state(self) -> Path:
        return self.root / ".hubicg"


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HubICGError(f"invalid JSON: {path}: {error}") from error


def safe_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise HubICGError(f"root is not a directory: {root}", EXIT_USAGE)
    return root


def inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def state_path(ctx: Context, *parts: str) -> Path:
    path = ctx.state.joinpath(*parts)
    if not inside(path, ctx.state):
        raise HubICGError("refusing path outside .hubicg", EXIT_USAGE)
    current = ctx.state
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise HubICGError(f"refusing symbolic link: {current}")
    return path


def emit(ctx: Context, payload: dict[str, Any], human: str) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True) if ctx.as_json else human)


def canonical(data: Any) -> bytes:
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode()


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode())
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def role_files(ctx: Context) -> list[Path]:
    directory = state_path(ctx, "roles")
    if not directory.exists():
        return []
    return sorted(p for p in directory.glob("*.json") if p.is_file() and not p.is_symlink())


def role_errors(path: Path) -> list[str]:
    data = read_json(path)
    if not isinstance(data, dict):
        return [f"{path}: role must be an object"]
    errors = []
    for field in ("id", "name", "instructions"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            errors.append(f"{path}: missing non-empty {field}")
    if data.get("schemaVersion") != "1.0":
        errors.append(f"{path}: schemaVersion must be 1.0")
    return errors


def validate(ctx: Context, _args: argparse.Namespace) -> None:
    errors = []
    config = state_path(ctx, "config.json")
    if not config.is_file():
        errors.append(".hubicg/config.json is missing")
    else:
        value = read_json(config)
        if not isinstance(value, dict) or value.get("schemaVersion") != "1.0":
            errors.append("config schemaVersion must be 1.0")
    files = role_files(ctx)
    if not files:
        errors.append("no roles found")
    for path in files:
        errors.extend(role_errors(path))
    if errors:
        raise HubICGError("; ".join(errors))
    emit(ctx, {"status": "valid", "roles": len(files)}, f"configuration=valid roles={len(files)}")


def status(ctx: Context, _args: argparse.Namespace) -> None:
    history = state_path(ctx, "history")
    proposals = state_path(ctx, "proposals")
    payload = {
        "root": str(ctx.root),
        "configured": state_path(ctx, "config.json").is_file(),
        "roles": len(role_files(ctx)),
        "historyFiles": len(list(history.glob("*.json"))) if history.exists() else 0,
        "pendingProposals": len(list(proposals.glob("*.json"))) if proposals.exists() else 0,
    }
    emit(ctx, payload, " ".join(f"{key}={value}" for key, value in payload.items()))


def roles_list(ctx: Context, _args: argparse.Namespace) -> None:
    roles = []
    for path in role_files(ctx):
        data = read_json(path)
        roles.append({"id": data.get("id"), "name": data.get("name"), "file": str(path.relative_to(ctx.root))})
    human = "\n".join(f"{role['id']}\t{role['name']}" for role in roles) or "no roles"
    emit(ctx, {"roles": roles}, human)


def roles_verify(ctx: Context, _args: argparse.Namespace) -> None:
    files = role_files(ctx)
    errors = [error for path in files for error in role_errors(path)]
    identifiers = [str(read_json(path).get("id")) for path in files]
    duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
    if duplicates:
        errors.append(f"duplicate role ids: {', '.join(duplicates)}")
    if errors:
        raise HubICGError("; ".join(errors))
    emit(ctx, {"status": "valid", "roles": len(files)}, f"roles=valid count={len(files)}")


def candidate(value: str) -> tuple[Path, Any]:
    path = Path(value).expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise HubICGError(f"candidate must be a regular file: {path}", EXIT_USAGE)
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schemaVersion") != "1.0":
        raise HubICGError("candidate schemaVersion must be 1.0")
    return path, data


def config_diff(ctx: Context, args: argparse.Namespace) -> None:
    candidate_path, after_data = candidate(args.candidate)
    active_path = state_path(ctx, "config.json")
    before_data = read_json(active_path) if active_path.is_file() else {}
    before = json.dumps(before_data, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    after = json.dumps(after_data, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    lines = list(difflib.unified_diff(before, after, fromfile=str(active_path), tofile=str(candidate_path), lineterm=""))
    emit(ctx, {"changed": bool(lines), "diff": lines}, "\n".join(lines) if lines else "configuration=unchanged")


def config_propose(ctx: Context, args: argparse.Namespace) -> None:
    source, data = candidate(args.candidate)
    proposal_id = hashlib.sha256(canonical(data)).hexdigest()[:16]
    proposal = {"schemaVersion": "1.0", "id": proposal_id, "source": source.name, "candidate": data}
    target = state_path(ctx, "proposals", f"{proposal_id}.json")
    atomic_json(target, proposal)
    emit(ctx, {"status": "pending", "proposalId": proposal_id, "file": str(target.relative_to(ctx.root))}, f"proposal=pending id={proposal_id}")


def config_apply(ctx: Context, args: argparse.Namespace) -> None:
    approval = args.approval.lower()
    if len(approval) != 16 or any(char not in "0123456789abcdef" for char in approval):
        raise HubICGError("a valid 16-character proposal ID is required", EXIT_APPROVAL)
    proposal_path = state_path(ctx, "proposals", f"{approval}.json")
    if not proposal_path.is_file():
        raise HubICGError("approved proposal was not found", EXIT_APPROVAL)
    proposal = read_json(proposal_path)
    data = proposal.get("candidate") if isinstance(proposal, dict) else None
    if proposal.get("id") != approval or hashlib.sha256(canonical(data)).hexdigest()[:16] != approval:
        raise HubICGError("proposal integrity check failed", EXIT_APPROVAL)
    atomic_json(state_path(ctx, "config.json"), data)
    proposal_path.unlink()
    emit(ctx, {"status": "applied", "proposalId": approval}, f"configuration=applied approval={approval}")


def history_verify(ctx: Context, _args: argparse.Namespace) -> None:
    directory = state_path(ctx, "history")
    files = sorted(directory.glob("*.json")) if directory.exists() else []
    errors, events = [], 0
    for path in files:
        data = read_json(path)
        messages = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(messages, list):
            errors.append(f"{path}: messages must be an array")
            continue
        for index, message in enumerate(messages):
            events += 1
            if not isinstance(message, dict) or message.get("role") not in {"user", "assistant", "system", "tool"}:
                errors.append(f"{path}: invalid message {index}")
    if errors:
        raise HubICGError("; ".join(errors))
    emit(ctx, {"status": "valid", "files": len(files), "messages": events}, f"history=valid files={len(files)} messages={events}")


def git_status(ctx: Context, _args: argparse.Namespace) -> None:
    try:
        result = subprocess.run(
            ["git", "status", "--short", "--branch"], cwd=ctx.root,
            capture_output=True, text=True, timeout=10, check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HubICGError(f"git status unavailable: {error}", EXIT_EXTERNAL) from error
    if result.returncode:
        raise HubICGError(result.stderr.strip() or "git status failed", EXIT_EXTERNAL)
    lines = result.stdout.splitlines()
    emit(ctx, {"status": lines, "clean": len(lines) <= 1}, result.stdout.rstrip())


def evidence_verify(ctx: Context, _args: argparse.Namespace) -> None:
    manifest = ctx.root / "MANIFEST.sha256"
    if not manifest.is_file():
        raise HubICGError("MANIFEST.sha256 is missing")
    checked, errors = 0, []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, separator, relative = line.partition("  ")
        target = (ctx.root / relative).resolve()
        if not separator or not inside(target, ctx.root) or not target.is_file() or target.is_symlink():
            errors.append(f"invalid manifest entry: {line}")
            continue
        checked += 1
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            errors.append(f"checksum mismatch: {relative}")
    if errors:
        raise HubICGError("; ".join(errors))
    emit(ctx, {"status": "valid", "files": checked}, f"evidence=valid files={checked}")


def build_parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="hubicg")
    result.add_argument("--root", default=".", help="project root")
    result.add_argument("--json", action="store_true")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("validate").set_defaults(handler=validate)
    commands.add_parser("status").set_defaults(handler=status)
    roles = commands.add_parser("roles").add_subparsers(dest="roles_command", required=True)
    roles.add_parser("list").set_defaults(handler=roles_list)
    roles.add_parser("verify").set_defaults(handler=roles_verify)
    config = commands.add_parser("config").add_subparsers(dest="config_command", required=True)
    diff = config.add_parser("diff"); diff.add_argument("candidate"); diff.set_defaults(handler=config_diff)
    propose = config.add_parser("propose"); propose.add_argument("candidate"); propose.set_defaults(handler=config_propose)
    apply = config.add_parser("apply"); apply.add_argument("--approval", required=True); apply.set_defaults(handler=config_apply)
    history = commands.add_parser("history").add_subparsers(dest="history_command", required=True)
    history.add_parser("verify").set_defaults(handler=history_verify)
    git = commands.add_parser("git").add_subparsers(dest="git_command", required=True)
    git.add_parser("status").set_defaults(handler=git_status)
    evidence = commands.add_parser("evidence").add_subparsers(dest="evidence_command", required=True)
    evidence.add_parser("verify").set_defaults(handler=evidence_verify)
    return result


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.handler(Context(safe_root(args.root), args.json), args)
    except HubICGError as error:
        message = {"status": "error", "error": str(error), "exitCode": error.code}
        print(json.dumps(message, ensure_ascii=False) if args.json else f"hubicg: {error}", file=sys.stderr)
        raise SystemExit(error.code) from error


if __name__ == "__main__":
    main()
