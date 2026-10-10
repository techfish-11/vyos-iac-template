from types import SimpleNamespace

import pytest

from vyos_iac.transaction import GuardError
from vyos_iac.transport import SSHTransport


@pytest.fixture
def transport(device, tmp_path):
    hosts = tmp_path / "known_hosts"
    hosts.write_text("")
    transport = SSHTransport(device, str(hosts), None, lambda *_: "", tmp_path)
    transport.lock_channel = SimpleNamespace(exit_status_ready=lambda: False)
    return transport


def test_host_keys_are_required(device, tmp_path):
    with pytest.raises(FileNotFoundError):
        SSHTransport(device, str(tmp_path / "missing"), None, lambda *_: "", tmp_path)


def test_new_ssh_probe_closes_its_own_connection(transport, monkeypatch):
    closed = []
    fresh = SimpleNamespace(close=lambda: closed.append(True))
    existing = object()
    transport.client = existing
    monkeypatch.setattr(transport, "connect", lambda: fresh)
    monkeypatch.setattr(transport, "execute", lambda client, _: {"fresh": client is fresh})
    assert transport.probe(fresh=True)["fresh"]
    assert closed == [True]
    assert transport.client is existing


def test_fresh_probe_closes_on_failure(transport, monkeypatch):
    closed = []
    monkeypatch.setattr(transport, "connect", lambda: SimpleNamespace(
        close=lambda: closed.append(True),
    ))

    def fail(*_):
        raise GuardError("probe failed")

    monkeypatch.setattr(transport, "execute", fail)
    with pytest.raises(GuardError):
        transport.probe(fresh=True)
    assert closed == [True]


def test_lost_lock_blocks_cli(transport):
    transport.lock_channel = SimpleNamespace(exit_status_ready=lambda: True)
    with pytest.raises(GuardError):
        transport.cli("commit-confirm 10", confirm=True)


@pytest.mark.parametrize("response", [
    "Invalid command: load", "Commit failed", "Error: bad configuration",
    "Another confirm is pending", "No confirm pending", "Cannot save configuration",
])
def test_cli_rejection_cannot_be_silently_accepted(transport, response):
    transport.cli_callback = lambda *_: response
    with pytest.raises(GuardError):
        transport.cli("save")
