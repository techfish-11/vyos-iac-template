"""Controller-only Ansible action. Configuration content never enters result output."""

import json
import os
import sys
from pathlib import Path

from ansible.plugins.action import ActionBase

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vyos_iac.artifacts import directory, report, write
from vyos_iac.config import MAX_CONFIG_BYTES, ROOT, ValidationError, render, source_path
from vyos_iac.messages import describe
from vyos_iac.transaction import Transaction
from vyos_iac.transport import SSHTransport


class ActionModule(ActionBase):
    _supports_check_mode = True
    _supports_async = False
    _requires_connection = True

    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)
        output = None
        try:
            args = self._task.args
            if set(args) - {"mode", "device", "known_hosts", "key_file", "minutes"}:
                raise ValueError("Unsupported action arguments")
            mode = args["mode"]
            if mode not in {"render", "plan", "apply", "backup", "save"}:
                raise ValueError("Invalid operation")
            # --check must never open a remote candidate session or create remote files.
            if self._task.check_mode and mode != "render":
                raise ValueError("Use render for offline checks, or plan for candidate review")
            if mode != "render":
                if (
                    os.name != "posix"
                    or self._play_context.connection != "ansible.netcommon.network_cli"
                ):
                    raise ValueError("Remote operations require Linux and network_cli")
                for name in ("ansible_password", "ansible_ssh_pass", "ansible_become_password"):
                    if task_vars.get(name):
                        raise ValueError("Password authentication is not supported")
                if task_vars.get("ansible_persistent_log_messages", False):
                    raise ValueError("Persistent connection logging must be disabled")
                if task_vars.get("ansible_host_key_checking") is not True:
                    raise ValueError("Host key checking must be enabled")
                if task_vars.get("ansible_host_key_auto_add", False):
                    raise ValueError("Automatic host key acceptance is forbidden")
                # Inspect effective plugin options too: environment/alias settings may
                # override the familiar inventory variable names.
                if (
                    not self._connection.get_option("host_key_checking")
                    or self._connection.get_option("host_key_auto_add")
                    or self._connection.get_option("persistent_log_messages")
                    or self._connection.get_option("persistent_command_timeout") > 60
                    or self._connection.get_option("ssh_type") != "paramiko"
                    or not self._connection.ssh_type_conn.get_option("host_key_checking")
                    or self._connection.ssh_type_conn.get_option("host_key_auto_add")
                ):
                    raise ValueError("Effective SSH or logging options are unsafe or unsupported")
                if mode in {"apply", "save"} and task_vars.get("ansible_limit", "") in {
                    "",
                    "all",
                    "*",
                    "vyos",
                }:
                    raise ValueError("An explicit device limit is required")
            device = args["device"]
            device = dict(device)
            secret_path = source_path(device["source"]).parent / "secrets.vault.yml"
            if secret_path.exists():
                if (
                    secret_path.is_symlink()
                    or not secret_path.resolve().is_relative_to(ROOT)
                    or secret_path.stat().st_size > MAX_CONFIG_BYTES
                ):
                    raise ValidationError(
                        "Vaultはリポジトリ内の1 MiB以下の通常ファイルにしてください。"
                    )
                if not secret_path.read_bytes().startswith(b"$ANSIBLE_VAULT;"):
                    raise ValidationError(
                        "secrets.vault.ymlをansible-vault encryptで暗号化してください。"
                    )
                try:
                    secret_data = self._loader.load_from_file(str(secret_path))
                except Exception as exc:
                    raise ValidationError(
                        "Vaultを復号できません。--ask-vault-passまたは--vault-password-fileを指定してください。"
                    ) from exc
                if not isinstance(secret_data, dict) or set(secret_data) != {"secrets"}:
                    raise ValidationError("Vaultにはsecrets:配下に秘密変数を記入してください。")
                if device["secrets"]:
                    raise ValidationError("秘密変数はsecrets.vault.ymlにまとめてください。")
                device["secrets"] = secret_data["secrets"]
            if mode != "render" and (
                device["host"] != self._play_context.remote_addr
                or device["user"] != self._play_context.remote_user
                or device["port"] != self._play_context.port
            ):
                raise ValueError("CLI and SFTP connection settings differ")
            content = render(device)
            output = directory(task_vars["inventory_hostname"])
            write(output / "config.boot", content)
            if mode == "render":
                result.update(changed=False, phase="completed", state="rendered")
            else:

                def cli(command, confirm):
                    module_args = {"command": command}
                    if confirm:
                        module_args.update(prompt=[r"[Pp]roceed.*\?"], answer=["y"])
                    response = self._execute_module(
                        module_name="ansible.netcommon.cli_command",
                        module_args=module_args,
                        task_vars=task_vars,
                    )
                    if response.get("failed") or "stdout" not in response:
                        raise RuntimeError("CLI transport failed")
                    return response["stdout"]

                transport = SSHTransport(
                    device,
                    args["known_hosts"],
                    args.get("key_file") or self._play_context.private_key_file,
                    cli,
                    output,
                )
                transaction = Transaction(transport, device, args.get("minutes", 10))
                result.update(transaction.run(mode, content))
            result["artifact_path"] = str(output)
            result["operation"] = mode
            result["source"] = device["source"]
            result["operation_failed"] = result.get("failed", False)
            result.update(describe(result, mode, task_vars["inventory_hostname"]))
            report(output, result)
        except Exception as exc:
            result.update(
                failed=True,
                phase=result.get("phase", "validation"),
                msg="Validation or execution failed; no secret details are logged",
            )
            if output is not None:
                result["artifact_path"] = str(output)
            if isinstance(exc, ValidationError):
                result["reason"] = str(exc)
        result["operation_failed"] = result.get("failed", False)
        result.update(
            describe(result, self._task.args.get("mode", "render"), task_vars["inventory_hostname"])
        )
        if task_vars.get("vyos_result_file"):
            try:
                write(Path(task_vars["vyos_result_file"]), json.dumps(result, ensure_ascii=False))
            except Exception:
                result.update(
                    failed=True,
                    operation_failed=True,
                    code="result_write_failed",
                    summary="実行結果を記録できませんでした。",
                    next_step="docs/recovery.mdで実機の状態を確認してください。",
                )
        return result
