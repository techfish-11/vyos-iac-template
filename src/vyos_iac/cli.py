"""Small, transparent interface over the same Ansible playbooks used directly."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


class CliError(Exception):
    def __init__(self, summary: str, next_step: str, code: str = "invalid_input"):
        super().__init__(summary)
        self.summary, self.next_step, self.code = summary, next_step, code


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="./vyos",
        description="VyOSの設定をそのまま書き、Ansibleで確認・投入します。",
        epilog="最初はsetup → list → check router01。README.mdも参照できます。",
    )
    commands = result.add_subparsers(dest="command")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="AI・スクリプト用のJSONを出力")
    common.add_argument("--inventory", default="inventory/hosts.yml", help="Ansible Inventory")
    for name, help_text in {
        "setup": "必要なPython環境とAnsible Collectionを準備",
        "doctor": "実行環境を確認（実機には接続しません）",
        "list": "機器と、編集する設定ファイルを表示",
        "check": "手元の設定の構造を確認（実機には接続しません）",
        "plan": "実機で候補をload・compare・破棄（まだ適用しません）",
        "apply": "全体置換し、SSH・設定・通信を検証して保存",
        "backup": "稼働設定と保存設定をバックアップ",
        "save": "確定済み設定の保存を復旧",
        "diff": "直近のplanで保存した差分を表示（秘密情報を含む場合があります）",
    }.items():
        command = commands.add_parser(name, help=help_text, description=help_text, parents=[common])
        if name in {"check", "plan", "apply", "backup", "save", "diff"}:
            command.add_argument(
                "device",
                nargs="?" if name == "check" else None,
                help="機器名。checkで省略すると全機器",
            )
        if name in {"check", "plan", "apply", "backup", "save"}:
            command.add_argument(
                "--ask-vault-pass", action="store_true", help="Vaultの復号鍵を入力"
            )
            command.add_argument("--vault-password-file", help="Git管理外のVault復号鍵ファイル")
            command.add_argument("--private-key", help="Git管理外のSSH秘密鍵")
    return result


def environment() -> dict[str, str]:
    return os.environ | {
        "ANSIBLE_CONFIG": str(ROOT / "src/ansible.cfg"),
        "ANSIBLE_HOME": str(ROOT / "src/.ansible"),
        "PYTHONIOENCODING": "utf-8",
    }


def executable(name: str) -> str:
    # sys.executable's directory also supports user-selected .venv-linux and CI environments.
    local = Path(sys.executable).parent / name
    found = str(local) if local.is_file() else shutil.which(name)
    if not found:
        raise CliError(
            "Ansibleの準備ができていません。", "./vyos setup を実行してください。", "setup_required"
        )
    return found


def inventory(path: str) -> dict[str, dict]:
    inventory_path = Path(path)
    if not inventory_path.is_absolute():
        inventory_path = ROOT / inventory_path
    if not inventory_path.is_file():
        raise CliError("Inventoryが見つかりません。", "--inventoryのパスを確認してください。")
    process = subprocess.run(
        [executable("ansible-inventory"), "-i", str(inventory_path), "--list"],
        cwd=ROOT,
        env=environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    if process.returncode:
        raise CliError(
            "Inventoryを読み込めません。", "inventory/hosts.ymlのYAMLと接続情報を確認してください。"
        )
    try:
        value = json.loads(process.stdout)
        names: set[str] = set()
        visited: set[str] = set()

        def visit(group):
            if group in visited:
                return
            visited.add(group)
            names.update(value[group].get("hosts", []))
            for child in value[group].get("children", []):
                visit(child)

        visit("vyos")
        if not names or any(not NAME.fullmatch(name) or name in value for name in names):
            raise ValueError
        return {name: value["_meta"]["hostvars"].get(name, {}) for name in sorted(names)}
    except (KeyError, ValueError, TypeError) as exc:
        raise CliError(
            "vyosグループに有効な機器がありません。",
            "inventory/hosts.ymlのrouter01の例を参照してください。",
        ) from exc


def device_data(name: str, variables: dict) -> dict:
    try:
        return {
            "host": variables["ansible_host"],
            "user": variables.get("ansible_user", "automation"),
            "port": variables.get("ansible_port", 22),
            "version": variables["vyos_version"],
            "source": variables.get("vyos_config_file", f"devices/{name}/config.boot"),
            "management_interface": variables["vyos_management_interface"],
            "healthcheck_targets": variables["vyos_healthcheck_targets"],
            "secrets": {},
        }
    except KeyError as exc:
        raise CliError(
            "機器の接続情報が不足しています。", "inventory/hosts.ymlの必須項目を確認してください。"
        ) from exc


def selected(args) -> dict[str, dict]:
    devices = inventory(args.inventory)
    name = getattr(args, "device", None)
    if name:
        if name in {"all", "ungrouped", "vyos"} or not NAME.fullmatch(name) or name not in devices:
            raise CliError(
                "その機器名は登録されていません。",
                "./vyos list で機器名を確認してください。",
                "unknown_device",
            )
        devices = {name: devices[name]}
    return devices


def artifact_root() -> Path:
    override = os.environ.get("VYOS_IAC_ARTIFACT_ROOT")
    state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return Path(override) if override else state / "vyos-iac"


def run_playbook(args, name: str, mode: str) -> dict:
    # Each invocation gets its own manifest: never identify results by newest-file races.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="vyos-iac-") as temp:
        manifest = Path(temp) / "result.json"
        command = [
            executable("ansible-playbook"),
            "-i",
            args.inventory,
            str(ROOT / f"src/playbooks/{mode}.yml"),
            "--limit",
            name,
            "--extra-vars",
            json.dumps({"vyos_result_file": str(manifest)}),
        ]
        for flag in ("ask_vault_pass", "vault_password_file", "private_key"):
            value = getattr(args, flag, None)
            if value:
                command.append("--" + flag.replace("_", "-"))
                if isinstance(value, str):
                    command.append(value)
        # Vault's prompt needs a real terminal. Machine mode must use a password file.
        interactive = bool(getattr(args, "ask_vault_pass", False))
        if interactive and args.json:
            raise CliError(
                "JSON出力では対話入力を使えません。", "--vault-password-fileを指定してください。"
            )
        if not args.json:
            print(
                f"{name}: Ansibleで{'構造確認' if mode == 'render' else mode}を実行中…", flush=True
            )
        process = subprocess.run(
            command,
            cwd=ROOT,
            env=environment(),
            check=False,
            stdout=None if interactive else subprocess.DEVNULL,
            stderr=None if interactive else subprocess.DEVNULL,
        )
        if not manifest.is_file():
            raise CliError(
                "Ansibleの処理を完了できませんでした。",
                "./vyos doctor を実行してください。投入中断の復旧はdocs/recovery.mdを参照。",
                "ansible_failed",
            )
        result = json.loads(manifest.read_text(encoding="utf-8"))
        if process.returncode:
            result["operation_failed"] = True
        return result | {"device": name}


def check(args, devices: dict[str, dict]) -> list[dict]:
    from vyos_iac.config import ValidationError, render, source_path
    from vyos_iac.messages import describe

    results = []
    for name, variables in devices.items():
        try:
            data = device_data(name, variables)
            source = source_path(data["source"])
            if source.name.endswith(".j2"):
                result = run_playbook(args, name, "render")
            else:
                render(data)
                result = {
                    "device": name,
                    "phase": "completed",
                    "state": "rendered",
                    "operation_failed": False,
                    "source": data["source"],
                }
                result.update(describe(result, "render", name))
        except ValidationError as exc:
            result = {
                "device": name,
                "operation_failed": True,
                "code": "invalid_config",
                "summary": str(exc),
                "next_step": "示された箇所を修正し、checkをやり直してください。",
            }
        results.append(result)
    return results


def doctor() -> list[dict]:
    checks = [
        ("Linux / WSL2", os.name == "posix", "WindowsではWSL2のターミナルから実行してください。"),
        ("Python 3.12以上", sys.version_info >= (3, 12), "Python 3.12以上を用意してください。"),
    ]
    for module in ("ansible", "yaml", "jinja2", "jsonschema", "paramiko"):
        checks.append(
            (
                module,
                importlib.util.find_spec(module) is not None,
                "./vyos setup を実行してください。",
            )
        )
    for namespace, name in (("ansible", "netcommon"), ("vyos", "vyos")):
        path = ROOT / "src/.collections/ansible_collections" / namespace / name / "MANIFEST.json"
        checks.append((f"{namespace}.{name}", path.is_file(), "./vyos setup を実行してください。"))
    return [
        {
            "device": label,
            "operation_failed": not ok,
            "summary": "準備できています。" if ok else hint,
            "code": "ready" if ok else "setup_required",
            "next_step": "" if ok else hint,
        }
        for label, ok, hint in checks
    ]


def setup(args) -> list[dict]:
    if args.json:
        raise CliError("setupは進行状況を表示する操作です。", "./vyos setup を実行してください。")
    if os.name != "posix" or sys.version_info < (3, 12):
        raise CliError(
            "Linux / WSL2とPython 3.12以上が必要です。", "docs/quickstart.mdを参照してください。"
        )
    venv = ROOT / "src/.venv"
    if (venv / "Scripts/python.exe").is_file():
        venv = ROOT / "src/.venv-linux"
    if venv.is_symlink():
        raise CliError(
            ".venvがシンボリックリンクです。", "リポジトリ内の専用仮想環境を使用してください。"
        )
    if not (venv / "bin/python").is_file():
        if venv.exists():
            raise CliError(
                ".venvをLinux環境として利用できません。",
                "Windows用の仮想環境は別の場所へ移してからsetupしてください。",
            )
        if subprocess.run([sys.executable, "-m", "venv", str(venv)], check=False).returncode:
            raise CliError(
                "Pythonの仮想環境を作成できません。",
                "Ubuntuではsudo apt install python3-venvを実行してください。",
            )
    commands = [
        [str(venv / "bin/python"), "-m", "pip", "install", "-r", "src/requirements.txt"],
        [
            str(venv / "bin/ansible-galaxy"),
            "collection",
            "install",
            "-r",
            "src/requirements.yml",
            "-p",
            str(ROOT / "src/.collections"),
        ],
    ]
    for number, command in enumerate(commands, 1):
        print(
            f"準備 {number}/2: {'Python依存関係' if number == 1 else 'Ansible Collection'}",
            flush=True,
        )
        if subprocess.run(command, cwd=ROOT, env=environment(), check=False).returncode:
            raise CliError(
                "準備を完了できませんでした。",
                "表示された接続・インストールエラーを解消し、setupを再実行してください。",
            )
    (ROOT / "vyos").chmod(0o755)
    return [
        {
            "device": "setup",
            "operation_failed": False,
            "code": "ready",
            "summary": "準備ができました。",
            "next_step": "./vyos list で編集する機器を確認してください。",
        }
    ]


def show(payload: dict, machine: bool) -> None:
    if machine:
        print(json.dumps(payload, ensure_ascii=False))
        return
    for row in payload["devices"]:
        status = "要確認" if row.get("operation_failed") else "OK"
        print(f"\n{row['device']}  {status}\n  {row['summary']}")
        for key, label in (
            ("source", "設定"),
            ("config_path", "確認箇所"),
            ("artifact_path", "保存先"),
            ("next_step", "次の操作"),
        ):
            if row.get(key):
                print(f"  {label}: {row[key]}")
        if "diff" in row:
            print(row["diff"])


def main(argv=None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    if not args.command:
        arguments.print_help()
        return 0
    try:
        if args.command == "setup":
            rows = setup(args)
        elif args.command == "doctor":
            rows = doctor()
        else:
            devices = selected(args)
            if args.command == "list":
                rows = [
                    {
                        "device": name,
                        "operation_failed": False,
                        "code": "listed",
                        "summary": (
                            f"VyOS {value.get('vyos_version', '?')} / "
                            f"{value.get('ansible_host', '?')}"
                        ),
                        "source": value.get("vyos_config_file", f"devices/{name}/config.boot"),
                        "next_step": f"設定を編集して ./vyos check {name} を実行してください。",
                    }
                    for name, value in devices.items()
                ]
            elif args.command == "check":
                rows = check(args, devices)
            elif args.command == "diff":
                name = next(iter(devices))
                # Only plans have a reviewable diff; never show an unrelated operation's file.
                candidates = []
                for report in (artifact_root() / name).glob("*/result.json"):
                    value = json.loads(report.read_text(encoding="utf-8"))
                    if value.get("operation") == "plan" and not value.get("operation_failed"):
                        candidates.append(report)
                if not candidates:
                    raise CliError(
                        "保存されたplanの差分がありません。",
                        f"./vyos plan {name} を先に実行してください。",
                    )
                latest = max(candidates, key=lambda path: path.stat().st_mtime_ns)
                difference = (latest.parent / "candidate.diff").read_text(encoding="utf-8")
                difference = "".join(
                    c if c in "\n\t" or ord(c) >= 32 and ord(c) != 127 else f"\\x{ord(c):02x}"
                    for c in difference
                )
                rows = [
                    {
                        "device": name,
                        "operation_failed": False,
                        "code": "diff",
                        "summary": "直近のplanの差分です。現在の実機状態は再取得していません。",
                        "artifact_path": str(latest.parent),
                        "diff": difference,
                    }
                ]
            else:
                rows = []
                for name in devices:
                    result = run_playbook(args, name, args.command)
                    rows.append(result)
                    if result.get("operation_failed"):
                        break
        ok = not any(row.get("operation_failed") for row in rows)
        show({"schema_version": 1, "operation": args.command, "ok": ok, "devices": rows}, args.json)
        return 0 if ok else 1
    except CliError as exc:
        row = {
            "device": getattr(args, "device", None) or args.command,
            "operation_failed": True,
            "summary": exc.summary,
            "next_step": exc.next_step,
            "code": exc.code,
        }
        show(
            {"schema_version": 1, "operation": args.command, "ok": False, "devices": [row]},
            args.json,
        )
        return 2
    except KeyboardInterrupt:
        print(
            "\n中断しました。投入中の場合はdocs/recovery.mdで実機の状態を確認してください。",
            file=sys.stderr,
        )
        return 130
    except (OSError, ValueError, ImportError, subprocess.TimeoutExpired):
        row = {
            "device": args.command,
            "operation_failed": True,
            "code": "environment_error",
            "summary": "ファイルまたは実行環境を確認できませんでした。",
            "next_step": "./vyos doctor とdocs/quickstart.mdを確認してください。",
        }
        show(
            {"schema_version": 1, "operation": args.command, "ok": False, "devices": [row]},
            args.json,
        )
        return 2
