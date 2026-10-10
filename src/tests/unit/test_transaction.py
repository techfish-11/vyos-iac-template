from copy import deepcopy

import pytest

from vyos_iac.transaction import GuardError, Transaction, canonical_commands

BASE_COMMANDS = "set system host-name 'old'\nset service ssh port '22'"
NEW_COMMANDS = 'set service ssh port "22"\nset system host-name "new"'


class FakeTransport:
    def __init__(self, device):
        self.calls = []
        self.fail = None
        self.sessions = 0
        self.pending = False
        self.changed = True
        self.current_commands = BASE_COMMANDS
        self.initial = {
            "system": {
                "host-name": "old",
                "login": {"user": {device["user"]: {"authentication": {"key": "same"}}}},
                "config-management": {"commit-confirm": {"action": "reload"},
                                      "commit-revisions": "100"},
            },
            "service": {"ssh": {"port": "22"}},
            "interfaces": {"ethernet": {"eth0": {"address": ["192.0.2.1/24"]}}},
        }
        self.running = deepcopy(self.initial)
        self.saved = deepcopy(self.initial)
        self.candidate = deepcopy(self.initial)
        self.candidate["system"]["host-name"] = "new"
        self.version = device["version"]
        self.reload_supported = True

    def call(self, name):
        self.calls.append(name)
        if self.fail == name:
            raise RuntimeError("TOP-SECRET transport failure")

    def lock(self):
        self.call("lock")

    def stage(self, content):
        self.call("stage")
        return "/tmp/vyos-iac-fixture/config.boot"

    def probe(self, fresh=False):
        self.call("fresh_probe" if fresh else "probe")
        return deepcopy({
            "version": self.version, "sessions": self.sessions, "pending": self.pending,
            "reload_supported": self.reload_supported, "running": self.running,
            "saved": self.saved, "candidate": self.candidate,
            "candidate_commands": NEW_COMMANDS if self.changed else BASE_COMMANDS,
            "running_commands": self.current_commands,
        })

    def cli(self, command, confirm=False):
        self.call(command)
        if command == "configure":
            self.sessions += 1
        elif command == "exit discard":
            self.sessions -= 1
        elif command == "show | commands":
            return NEW_COMMANDS if self.changed else BASE_COMMANDS
        elif command.startswith("commit-confirm"):
            self.pending = True
            self.running = deepcopy(self.candidate)
            self.current_commands = NEW_COMMANDS
        elif command == "confirm":
            self.pending = False
        elif command == "save":
            self.saved = deepcopy(self.running)
        return ""

    def backup(self, snapshot):
        self.call("backup")

    def diff(self, text):
        self.call("diff")

    def ping(self, targets):
        self.call("ping")

    def cleanup(self):
        self.call("cleanup")


def test_success_has_fresh_authentication_before_confirm(device):
    transport = FakeTransport(device)
    result = Transaction(transport, device).run("apply", "candidate")
    assert not result.get("failed")
    assert result["state"] == "saved"
    assert transport.calls.index("fresh_probe") < transport.calls.index("confirm")
    assert transport.calls.index("ping") < transport.calls.index("confirm")
    assert transport.calls.index("confirm") < transport.calls.index("save")
    assert transport.sessions == 0


@pytest.mark.parametrize("mode", ["plan", "apply"])
def test_no_changes_never_commit_or_save(device, mode):
    transport = FakeTransport(device)
    transport.changed = False
    transport.candidate = deepcopy(transport.initial)
    result = Transaction(transport, device).run(mode, "candidate")
    assert result["changed"] is False
    assert not result["would_change"]
    assert "save" not in transport.calls
    assert "confirm" not in transport.calls


def test_plan_discards_without_committing(device):
    transport = FakeTransport(device)
    result = Transaction(transport, device).run("plan", "candidate")
    assert result["would_change"] is True
    assert result["changed"] is False
    assert "save" not in transport.calls
    assert "commit-confirm 10" not in transport.calls
    assert transport.running == transport.initial
    assert transport.saved == transport.initial
    assert transport.calls[-2:] == ["exit discard", "cleanup"]


@pytest.mark.parametrize("failure,phase,state", [
    ("lock", "lock", "unchanged"),
    ("stage", "stage", "unchanged"),
    ("probe", "preflight", "unchanged"),
    ("configure", "configure", "unchanged"),
    ("load /tmp/vyos-iac-fixture/config.boot", "load", "unchanged"),
    ("commit-confirm 10", "commit_confirm", "commit_outcome_unknown"),
    ("ping", "verify", "awaiting_rollback"),
    ("fresh_probe", "verify", "awaiting_rollback"),
    ("confirm", "confirm", "confirm_outcome_unknown"),
    ("save", "save", "applied_not_saved"),
])
def test_failure_stops_transaction_and_redacts(device, failure, phase, state):
    transport = FakeTransport(device)
    transport.fail = failure
    result = Transaction(transport, device).run("apply", "candidate")
    assert result["failed"] is True
    assert result["phase"] == phase
    assert result["state"] == state
    assert "TOP-SECRET" not in str(result)
    assert transport.calls[-1] == "cleanup"
    if phase in {"lock", "stage", "preflight", "configure", "load", "commit_confirm", "verify"}:
        assert "confirm" not in transport.calls
        assert "save" not in transport.calls


@pytest.mark.parametrize(
    "violation", ["version", "pending", "session", "reload", "management", "unsaved"],
)
def test_preflight_guard_never_enters_configuration(device, violation):
    transport = FakeTransport(device)
    if violation == "version":
        transport.version = "1.5"
    elif violation == "pending":
        transport.pending = True
    elif violation == "session":
        transport.sessions = 1
    elif violation == "reload":
        transport.reload_supported = False
    elif violation == "management":
        transport.candidate["service"]["ssh"]["port"] = "2222"
    else:
        transport.saved["system"]["host-name"] = "unsaved"
    result = Transaction(transport, device).run("apply", "candidate")
    assert result["failed"]
    assert "configure" not in transport.calls


@pytest.mark.parametrize("failure", ["exit discard", "cleanup"])
def test_cleanup_failure_is_not_swallowed(device, failure):
    transport = FakeTransport(device)
    transport.fail = failure
    result = Transaction(transport, device).run("plan", "candidate")
    assert result["failed"]


def test_save_recovery_requires_exact_reviewed_configuration(device):
    transport = FakeTransport(device)
    transport.running = deepcopy(transport.candidate)
    transport.current_commands = NEW_COMMANDS
    result = Transaction(transport, device).run("save", "candidate")
    assert result["state"] == "saved"
    assert not result.get("failed")
    assert "load /tmp/vyos-iac-fixture/config.boot" not in transport.calls
    assert "commit-confirm 10" not in transport.calls


def test_save_recovery_rejects_wrong_candidate(device):
    transport = FakeTransport(device)
    result = Transaction(transport, device).run("save", "candidate")
    assert result["failed"]
    assert "save" not in transport.calls


def test_save_recovery_failure_reports_applied_not_saved(device):
    transport = FakeTransport(device)
    transport.running = deepcopy(transport.candidate)
    transport.current_commands = NEW_COMMANDS
    transport.fail = "save"
    result = Transaction(transport, device).run("save", "candidate")
    assert result["failed"]
    assert result["state"] == "applied_not_saved"


def test_configuration_commands_ignore_order_and_quote_style():
    first = "set system host-name 'router'\nset service ssh port '22'"
    second = 'set service ssh port "22"\nset system host-name "router"\n[edit]'
    assert canonical_commands(first) == canonical_commands(second)
    with pytest.raises(GuardError):
        canonical_commands("syntax error")


def test_ansible_integer_subclasses_are_supported(device):
    class TaggedInt(int):
        pass

    result = Transaction(FakeTransport(device), device, TaggedInt(10)).run("plan", "candidate")
    assert not result.get("failed")


def test_loaded_candidate_mismatch_is_rejected_before_commit(device):
    transport = FakeTransport(device)
    original_cli = transport.cli

    def incomplete_load(command, confirm=False):
        if command == "show | commands":
            return BASE_COMMANDS
        return original_cli(command, confirm)

    transport.cli = incomplete_load
    result = Transaction(transport, device).run("apply", "candidate")
    assert result["failed"]
    assert "commit-confirm 10" not in transport.calls


def test_rollback_during_verification_prevents_confirmation(device):
    transport = FakeTransport(device)
    original_probe = transport.probe

    def reverted_probe(fresh=False):
        if fresh:
            transport.running = deepcopy(transport.initial)
            transport.current_commands = BASE_COMMANDS
            transport.pending = False
        return original_probe(fresh)

    transport.probe = reverted_probe
    result = Transaction(transport, device).run("apply", "candidate")
    assert result["failed"]
    assert "confirm" not in transport.calls
    assert "save" not in transport.calls
