import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fcntl", reason="Ansible controller requires Linux")


@pytest.fixture
def action_module(monkeypatch):
    spec = importlib.util.spec_from_file_location("iac_action", "src/plugins/action/vyos_iac.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.ActionBase, "run", lambda *_: {})
    return module


def action(module, device, mode, tmp_path):
    instance = object.__new__(module.ActionModule)
    instance._task = SimpleNamespace(args={
        "mode": mode, "device": device, "known_hosts": str(tmp_path / "known_hosts"),
    }, check_mode=False)
    instance._play_context = SimpleNamespace(
        connection="ansible.netcommon.network_cli", remote_addr=device["host"],
        remote_user=device["user"], port=device["port"], private_key_file=None,
    )
    options = {"host_key_checking": True, "host_key_auto_add": False,
               "persistent_log_messages": False, "persistent_command_timeout": 60,
               "ssh_type": "paramiko"}
    instance._connection = SimpleNamespace(
        get_option=options.get, ssh_type_conn=SimpleNamespace(get_option=options.get),
    )
    return instance


def task_vars():
    return {
        "inventory_hostname": "fixture", "ansible_host_key_checking": True,
        "ansible_limit": "fixture",
    }


def test_failed_operation_keeps_independent_failure_flag(
    action_module, device, tmp_path, monkeypatch,
):
    module = action_module
    monkeypatch.setattr(module, "directory", lambda _: tmp_path)
    monkeypatch.setattr(module, "SSHTransport", lambda *_: object())
    monkeypatch.setattr(module, "Transaction", lambda *_: SimpleNamespace(run=lambda *_: {
        "failed": True, "changed": True, "phase": "save", "state": "applied_not_saved",
    }))
    result = action(module, device, "apply", tmp_path).run(task_vars=task_vars())
    # Ansible's failed_when:false may reset failed, but must not erase this flag.
    assert result["operation_failed"] is True
    assert result["state"] == "applied_not_saved"
    assert (tmp_path / "result.json").exists()


def test_render_does_not_construct_remote_transport(action_module, device, tmp_path, monkeypatch):
    monkeypatch.setattr(action_module, "directory", lambda _: tmp_path)

    def no_remote(*_):
        pytest.fail("Offline rendering attempted an SSH connection")

    monkeypatch.setattr(action_module, "SSHTransport", no_remote)
    result = action(action_module, device, "render", tmp_path).run(task_vars=task_vars())
    assert result["state"] == "rendered"
    assert result["operation_failed"] is False


@pytest.mark.parametrize("override", [
    {"ansible_host_key_checking": False},
    {"ansible_persistent_log_messages": True},
    {"ansible_host_key_auto_add": True},
    {"ansible_password": "SECRET"},
    {"ansible_limit": ""},
])
def test_unsafe_runtime_settings_rejected_before_artifacts(
    action_module, device, tmp_path, override,
):
    variables = task_vars() | override
    result = action(action_module, device, "apply", tmp_path).run(task_vars=variables)
    assert result["operation_failed"]
    assert "SECRET" not in str(result)
    assert list(tmp_path.iterdir()) == []


def test_check_mode_rejects_remote_planning(action_module, device, tmp_path):
    instance = action(action_module, device, "plan", tmp_path)
    instance._task.check_mode = True
    result = instance.run(task_vars=task_vars())
    assert result["operation_failed"]
    assert not Path(tmp_path / "config.boot").exists()


def test_effective_host_key_override_is_rejected(action_module, device, tmp_path):
    instance = action(action_module, device, "apply", tmp_path)
    instance._connection.get_option = lambda key: False if key == "host_key_checking" else None
    result = instance.run(task_vars=task_vars())
    assert result["operation_failed"]
    assert not Path(tmp_path / "config.boot").exists()


def test_cli_receives_failure_manifest_before_artifacts_exist(action_module, device, tmp_path):
    manifest = tmp_path / "cli.json"
    variables = task_vars() | {"ansible_password": "SECRET", "vyos_result_file": str(manifest)}
    result = action(action_module, device, "apply", tmp_path).run(task_vars=variables)
    assert result["operation_failed"]
    recorded = json.loads(manifest.read_text())
    assert recorded["operation_failed"]
    assert "SECRET" not in str(recorded)


def test_offline_manifest_and_report_have_operation(action_module, device, tmp_path, monkeypatch):
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(action_module, "directory", lambda _: output)
    manifest = tmp_path / "cli.json"
    variables = task_vars() | {"vyos_result_file": str(manifest)}
    result = action(action_module, device, "render", tmp_path).run(task_vars=variables)
    assert not result["operation_failed"]
    for path in [manifest, output / "result.json"]:
        recorded = json.loads(path.read_text())
        assert recorded["operation"] == "render"
        assert recorded["source"] == device["source"]


@pytest.mark.parametrize("valid_key", [True, False])
def test_real_vault_loader_keeps_secret_out_of_results(
    action_module, device, tmp_path, monkeypatch, valid_key,
):
    from ansible.parsing.dataloader import DataLoader
    from ansible.parsing.vault import VaultLib, VaultSecret

    from vyos_iac import config

    schema = config.ROOT / "src/schemas/device.json"
    (tmp_path / "src/schemas").mkdir(parents=True)
    (tmp_path / "src/schemas/device.json").write_bytes(schema.read_bytes())
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(action_module, "ROOT", tmp_path)
    device["source"] = "config.boot"
    (tmp_path / "config.boot.j2").write_text(
        "system { value {{ secrets.hash | vyos_quote }} }", encoding="utf-8",
    )
    key = VaultSecret(b"unit-test-only")
    encrypted = VaultLib().encrypt(b"secrets:\n  hash: PRIVATE_TEST_VALUE\n", secret=key)
    (tmp_path / "secrets.vault.yml").write_bytes(encrypted)
    output = tmp_path / "artifacts"
    output.mkdir()
    monkeypatch.setattr(action_module, "directory", lambda _: output)
    instance = action(action_module, device, "render", tmp_path)
    instance._loader = DataLoader()
    instance._loader.set_vault_secrets([
        ("default", key if valid_key else VaultSecret(b"incorrect")),
    ])
    result = instance.run(task_vars=task_vars())
    assert result["operation_failed"] is not valid_key
    assert "PRIVATE_TEST_VALUE" not in str(result)
    if valid_key:
        assert '"PRIVATE_TEST_VALUE"' in (output / "config.boot").read_text()
    else:
        assert list(output.iterdir()) == []
