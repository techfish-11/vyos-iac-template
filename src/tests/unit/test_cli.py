import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from vyos_iac import cli


@pytest.fixture
def devices(monkeypatch):
    value = {"router01": {
        "ansible_host": "192.0.2.1", "ansible_user": "automation", "ansible_port": 22,
        "vyos_version": "1.4", "vyos_management_interface": "eth0",
        "vyos_healthcheck_targets": ["192.0.2.254"],
    }}
    monkeypatch.setattr(cli, "inventory", lambda _: value)
    return value


def test_check_is_offline_and_json_is_one_document(devices, monkeypatch, capsys):
    def no_remote(*_):
        pytest.fail("Native check must not execute a playbook")

    monkeypatch.setattr(cli, "run_playbook", no_remote)
    assert cli.main(["check", "router01", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] and result["schema_version"] == 1
    assert result["devices"][0]["source"] == "devices/router01/config.boot"
    assert result["devices"][0]["code"] == "checked"
    assert "public-keys" not in str(result)


@pytest.mark.parametrize("name", ["all", "*", "router*", "router02", "--limit=all"])
def test_unknown_target_cannot_start_deployment(devices, monkeypatch, capsys, name):
    monkeypatch.setattr(cli, "run_playbook", lambda *_: pytest.fail("Deployment started"))
    assert cli.main(["apply", "--json", "--", name]) == 2
    result = json.loads(capsys.readouterr().out)
    assert not result["ok"]
    assert result["devices"][0]["code"] == "unknown_device"


@pytest.mark.parametrize("operation", ["plan", "apply", "backup", "save", "diff"])
def test_remote_operation_requires_device(operation):
    with pytest.raises(SystemExit) as error:
        cli.parser().parse_args([operation])
    assert error.value.code == 2


def test_list_points_to_native_config(devices, capsys):
    assert cli.main(["list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["devices"][0]["source"].endswith("config.boot")


def test_inventory_host_named_all_cannot_bypass_explicit_target(devices, monkeypatch, capsys):
    devices["all"] = devices["router01"]
    monkeypatch.setattr(cli, "run_playbook", lambda *_: pytest.fail("Deployment started"))
    assert cli.main(["apply", "all", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["devices"][0]["code"] == "unknown_device"


def test_playbook_target_and_manifest_are_specific(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "executable", lambda _: "/venv/bin/ansible-playbook")

    def execute(command, **kwargs):
        calls.append(command)
        assert command[command.index("--limit") + 1] == "router01"
        assert str(cli.ROOT / "src/playbooks/apply.yml") in command
        assert kwargs["env"]["ANSIBLE_CONFIG"] == str(cli.ROOT / "src/ansible.cfg")
        assert kwargs["stdout"] == subprocess.DEVNULL
        manifest = json.loads(command[command.index("--extra-vars") + 1])["vyos_result_file"]
        Path(manifest).write_text(json.dumps({"operation_failed": False, "code": "saved"}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", execute)
    args = cli.parser().parse_args([
        "apply", "router01", "--json", "--private-key", "/private/key",
        "--vault-password-file", "/private/vault",
    ])
    result = cli.run_playbook(args, "router01", "apply")
    assert result["device"] == "router01" and result["code"] == "saved"
    assert "--private-key" in calls[0] and "--vault-password-file" in calls[0]
    assert capsys.readouterr().out == ""


def test_nonzero_ansible_exit_cannot_be_success(monkeypatch):
    monkeypatch.setattr(cli, "executable", lambda _: "/ansible-playbook")

    def execute(command, **_):
        manifest = json.loads(command[command.index("--extra-vars") + 1])["vyos_result_file"]
        Path(manifest).write_text('{"operation_failed": false}')
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(cli.subprocess, "run", execute)
    args = cli.parser().parse_args(["apply", "router01", "--json"])
    assert cli.run_playbook(args, "router01", "apply")["operation_failed"]


def test_json_vault_prompt_rejected_before_subprocess(monkeypatch):
    monkeypatch.setattr(cli, "executable", lambda _: "/ansible-playbook")
    monkeypatch.setattr(cli.subprocess, "run", lambda *_: pytest.fail("Prompt started"))
    args = cli.parser().parse_args(["apply", "router01", "--json", "--ask-vault-pass"])
    with pytest.raises(cli.CliError):
        cli.run_playbook(args, "router01", "apply")


def test_no_manifest_never_uses_previous_run(monkeypatch):
    monkeypatch.setattr(cli, "executable", lambda _: "/ansible-playbook")
    monkeypatch.setattr(cli.subprocess, "run", lambda *_, **__: SimpleNamespace(returncode=2))
    args = cli.parser().parse_args(["plan", "router01", "--json"])
    with pytest.raises(cli.CliError) as error:
        cli.run_playbook(args, "router01", "plan")
    assert error.value.code == "ansible_failed"


def test_malformed_config_reports_location_not_values(devices, monkeypatch, capsys):
    from vyos_iac import config

    def invalid(*_):
        config.check_structure('system {\n host-name "private-value\n}', "config.boot")

    monkeypatch.setattr(config, "render", invalid)
    assert cli.main(["check", "router01", "--json"]) == 1
    output = capsys.readouterr().out
    assert "private-value" not in output
    assert "config.boot:2" in json.loads(output)["devices"][0]["summary"]


def test_diff_only_reads_successful_plan(devices, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "artifact_root", lambda: tmp_path)
    for run, operation, failed in [("old", "plan", False), ("new", "apply", False),
                                   ("failed", "plan", True)]:
        folder = tmp_path / "router01" / run
        folder.mkdir(parents=True)
        (folder / "result.json").write_text(json.dumps({
            "operation": operation, "operation_failed": failed,
        }))
        (folder / "candidate.diff").write_text(f"{run}\x1b[31m")
    assert cli.main(["diff", "router01", "--json"]) == 0
    difference = json.loads(capsys.readouterr().out)["devices"][0]["diff"]
    assert difference == "old\\x1b[31m"
