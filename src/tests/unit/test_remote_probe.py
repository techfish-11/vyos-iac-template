import importlib

import pytest

pytest.importorskip("fcntl", reason="VyOS helper requires Linux")

remote_probe = importlib.import_module("vyos_iac.remote_probe")


def test_semantic_normalization_handles_multivalue_order():
    assert remote_probe.normalize({"address": ["b", "a"]}) == {"address": ["a", "b"]}


def test_failed_helper_never_prints_secret(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["probe.py", "probe", "--candidate", "/tmp/candidate"])

    def fail(*_):
        raise RuntimeError("SECRET-PASSWORD")

    monkeypatch.setattr(remote_probe, "probe", fail)
    assert remote_probe.main() == 1
    assert "SECRET-PASSWORD" not in capsys.readouterr().out


def test_invalid_ping_target_is_not_executed(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("sys.argv", ["probe.py", "ping", "--targets", "-c100"])
    monkeypatch.setattr(remote_probe, "execute", lambda argv: calls.append(argv))
    assert remote_probe.main() == 1
    assert calls == []
    assert "error" in capsys.readouterr().out
