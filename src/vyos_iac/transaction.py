"""Transaction state machine, isolated from Ansible and SSH for failure testing."""

from __future__ import annotations

import shlex
import time
from dataclasses import dataclass
from typing import Any, Protocol


class GuardError(RuntimeError):
    """A violated safety invariant; message must not contain configuration values."""

    def __init__(self, message: str, config_path: str | None = None):
        super().__init__(message)
        self.config_path = config_path


def canonical_commands(text: str) -> frozenset[tuple[str, ...]]:
    commands = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line == "[edit]":
            continue
        tokens = tuple(shlex.split(line))
        if not tokens or tokens[0] != "set" or len(tokens) < 3:
            raise GuardError("Unexpected configuration command output")
        commands.add(tokens)
    if not commands:
        raise GuardError("Empty configuration command output")
    return frozenset(commands)


def lookup(tree: dict, *path: str) -> Any:
    node: Any = tree
    for part in path:
        if not isinstance(node, dict) or part not in node:
            raise GuardError("Required management configuration is missing", "/" + "/".join(path))
        node = node[part]
    return node


def guard(snapshot: dict, device: dict, sessions: int, pending: bool = False) -> None:
    if snapshot["version"] != device["version"]:
        raise GuardError("Device version does not match inventory")
    if snapshot["sessions"] != sessions:
        raise GuardError("Conflicting or unrecognised configuration session")
    if snapshot["pending"] is not pending:
        raise GuardError("Unexpected commit-confirm timer state")
    if not snapshot["reload_supported"]:
        raise GuardError("This build does not support soft commit-confirm rollback")
    before, after = snapshot["running"], snapshot["candidate"]
    for path in [
        ("service", "ssh"),
        ("system", "login", "user", device["user"]),
        ("interfaces", "ethernet", device["management_interface"]),
    ]:
        if lookup(before, *path) != lookup(after, *path):
            raise GuardError(
                "Management connection configuration must remain unchanged",
                "/" + "/".join(path),
            )
    for tree in (before, after):
        action = lookup(tree, "system", "config-management", "commit-confirm", "action")
        if action != "reload":
            raise GuardError("commit-confirm action reload is required")
        revisions = lookup(tree, "system", "config-management", "commit-revisions")
        if int(revisions) < 2:
            raise GuardError("At least two commit revisions are required for rollback")


class Transport(Protocol):
    def lock(self) -> None: ...
    def stage(self, content: str) -> str: ...
    def probe(self, fresh: bool = False) -> dict: ...
    def cli(self, command: str, confirm: bool = False) -> str: ...
    def backup(self, snapshot: dict) -> None: ...
    def diff(self, text: str) -> None: ...
    def ping(self, targets: list[str]) -> None: ...
    def cleanup(self) -> None: ...


@dataclass
class Transaction:
    transport: Transport
    device: dict
    minutes: int = 10

    def run(self, mode: str, content: str) -> dict:
        if mode not in {"plan", "apply", "backup", "save"}:
            raise GuardError("Unsupported operation")
        if (
            not isinstance(self.minutes, int)
            or isinstance(self.minutes, bool)
            or not 2 <= self.minutes <= 30
        ):
            raise GuardError("Commit timeout must be an integer from 2 to 30 minutes")
        result = {"changed": False, "phase": "lock", "state": "unchanged"}
        entered = False
        try:
            self.transport.lock()
            result["phase"] = "stage"
            path = self.transport.stage(content)
            result["phase"] = "preflight"
            initial = self.transport.probe()
            guard(initial, self.device, sessions=0)
            self.transport.backup(initial)
            if mode == "backup":
                result["phase"] = "completed"
                return result
            if mode != "save" and initial["running"] != initial["saved"]:
                raise GuardError("Running configuration has unsaved changes")
            result["phase"] = "configure"
            # Set before sending: a timeout may occur after the device entered config mode.
            entered = True
            self.transport.cli("configure")
            guard(self.transport.probe(), self.device, sessions=1)
            if mode == "save":
                result["phase"] = "verify"
                if initial["running"] != initial["candidate"]:
                    raise GuardError("Save recovery requires the reviewed running configuration")
                self.transport.ping(self.device["healthcheck_targets"])
                current = self.transport.probe(fresh=True)
                guard(current, self.device, sessions=1)
                if current["running"] != initial["running"]:
                    raise GuardError("Configuration changed during save recovery")
                result["changed"] = initial["running"] != initial["saved"]
                result["state"] = "applied_not_saved" if result["changed"] else "saved"
            else:
                result["phase"] = "load"
                self.transport.cli(f"load {path}")
                expected = canonical_commands(self.transport.cli("show | commands"))
                difference = self.transport.cli("compare")
                self.transport.diff(difference)
                current = self.transport.probe()
                guard(current, self.device, sessions=1)
                if expected != canonical_commands(current["candidate_commands"]):
                    raise GuardError("Loaded candidate does not match the generated file")
                if current["running"] != initial["running"]:
                    raise GuardError("Running configuration changed during planning")
                changed = expected != canonical_commands(initial["running_commands"])
                if mode == "plan" or not changed:
                    result["would_change"] = changed
                    result["phase"] = "completed"
                    return result
                result.update(phase="commit_confirm", changed=True, state="commit_outcome_unknown")
                started = time.monotonic()
                self.transport.cli(f"commit-confirm {self.minutes}", confirm=True)
                result.update(phase="verify", state="awaiting_rollback")
                self.transport.ping(self.device["healthcheck_targets"])
                verified = self.transport.probe(fresh=True)
                guard(verified, self.device, sessions=1, pending=True)
                if canonical_commands(verified["running_commands"]) != expected:
                    raise GuardError("Applied configuration does not match the candidate")
                # Leave a full command timeout plus margin; never confirm at the timer boundary.
                if time.monotonic() - started >= self.minutes * 60 - 90:
                    raise GuardError("Verification exceeded the safe confirmation deadline")
                result.update(phase="confirm", state="confirm_outcome_unknown")
                self.transport.cli("confirm")
                result["state"] = "applied_not_saved"
                confirmed = self.transport.probe()
                guard(confirmed, self.device, sessions=1)
                if canonical_commands(confirmed["running_commands"]) != expected:
                    raise GuardError("Configuration changed during confirmation")
            result["phase"] = "save"
            self.transport.cli("save")
            result["phase"] = "verify_saved"
            saved = self.transport.probe()
            guard(saved, self.device, sessions=1)
            if saved["running"] != saved["saved"]:
                raise GuardError("Saved configuration verification failed")
            if mode != "save" and canonical_commands(saved["running_commands"]) != expected:
                raise GuardError("Configuration changed during save")
            if mode == "save" and saved["running"] != initial["running"]:
                raise GuardError("Configuration changed during save recovery")
            result.update(phase="completed", state="saved")
        except Exception as exc:
            # Deliberately redact transport/CLI exceptions: they can contain complete secrets.
            result.update(failed=True, msg="Operation failed; inspect phase and recovery state")
            if isinstance(exc, GuardError):
                result["reason"] = str(exc)
                if exc.config_path:
                    result["config_path"] = exc.config_path
        finally:
            if entered:
                try:
                    self.transport.cli("exit discard")
                except Exception:
                    result.update(failed=True, session_cleanup_failed=True)
            try:
                self.transport.cleanup()
            except Exception:
                result.update(failed=True, artifact_cleanup_failed=True)
        return result
