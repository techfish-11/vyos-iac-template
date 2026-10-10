"""Host-key-verified SFTP transport alongside Ansible's persistent CLI session."""

from __future__ import annotations

import json
import re
import shlex
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import paramiko

from vyos_iac.artifacts import write
from vyos_iac.transaction import GuardError


class SSHTransport:
    def __init__(
        self, device: dict, known_hosts: str, key_file: str | None,
        cli: Callable, output: Path,
    ):
        self.device = device
        self.known_hosts = str(Path(known_hosts).expanduser().resolve(strict=True))
        self.key_file = str(Path(key_file).expanduser().resolve(strict=True)) if key_file else None
        self.cli_callback = cli
        self.output = output
        self.client = None
        self.sftp = None
        self.lock_channel = None
        self.remote = "/tmp/vyos-iac-" + uuid.uuid4().hex
        self.created = False
        self.candidate = self.remote + "/config.boot"

    def connect(self):
        client = paramiko.SSHClient()
        client.load_host_keys(self.known_hosts)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(
                hostname=self.device["host"], port=self.device["port"],
                username=self.device["user"], key_filename=self.key_file,
                look_for_keys=False, allow_agent=True, timeout=30,
                auth_timeout=30, banner_timeout=30,
            )
        except Exception:
            client.close()
            raise
        return client

    def command(self, operation: str, arguments: list[str] | None = None) -> str:
        return shlex.join([
            "/usr/bin/python3", self.remote + "/probe.py", operation, *(arguments or []),
        ])

    @staticmethod
    def execute(client, command: str) -> dict:
        stdin, stdout, stderr = client.exec_command(command, timeout=30)
        stdin.close()
        try:
            # Bound output and consume both streams without pipe deadlocks.
            channel = stdout.channel
            deadline = time.monotonic() + 30
            data = bytearray()
            error_size = 0
            while True:
                while channel.recv_ready():
                    data.extend(channel.recv(65536))
                    if len(data) > 8 * 1024 * 1024:
                        raise GuardError("Remote response exceeds the size limit")
                while channel.recv_stderr_ready():
                    error_size += len(channel.recv_stderr(65536))
                    if error_size > 1024 * 1024:
                        raise GuardError("Remote error response exceeds the size limit")
                if channel.exit_status_ready() and not channel.recv_ready():
                    break
                if time.monotonic() >= deadline:
                    raise GuardError("Remote command timed out")
                time.sleep(0.02)
            if channel.recv_exit_status() != 0:
                raise GuardError("Remote validation or capability check failed")
            result = json.loads(data.decode("utf-8"))
            if not isinstance(result, dict) or "error" in result:
                raise GuardError("Invalid remote response")
            return result
        finally:
            stdout.close()
            stderr.close()
            stdout.channel.close()

    def lock(self) -> None:
        self.client = self.connect()
        self.sftp = self.client.open_sftp()
        self.sftp.get_channel().settimeout(30)
        self.sftp.mkdir(self.remote, mode=0o700)
        self.created = True
        self.sftp.chmod(self.remote, 0o700)
        self.upload(
            "probe.py", Path(__file__).with_name("remote_probe.py").read_text(encoding="utf-8"),
        )
        transport = self.client.get_transport()
        if transport is None:
            raise GuardError("SSH transport is unavailable")
        self.lock_channel = transport.open_session(timeout=30)
        self.lock_channel.settimeout(30)
        self.lock_channel.exec_command(self.command("lock"))
        reply = bytearray()
        while b"\n" not in reply:
            part = self.lock_channel.recv(64)
            if not part or len(reply) + len(part) > 128:
                raise GuardError("Cannot acquire the device lock")
            reply.extend(part)
        if bytes(reply).strip() != b"LOCKED":
            raise GuardError("Cannot acquire the device lock")

    def assert_lock(self):
        if self.lock_channel is None or self.lock_channel.exit_status_ready():
            raise GuardError("Device lock was lost")

    def upload(self, name: str, content: str) -> None:
        if self.sftp is None or name not in {"probe.py", "config.boot"}:
            raise GuardError("Invalid staging operation")
        with self.sftp.open(self.remote + "/" + name, "wx") as stream:
            stream.write(content.encode("utf-8"))
        self.sftp.chmod(self.remote + "/" + name, 0o600)

    def stage(self, content: str) -> str:
        self.assert_lock()
        self.upload("config.boot", content)
        return self.candidate

    def probe(self, fresh: bool = False) -> dict:
        self.assert_lock()
        client = self.connect() if fresh else self.client
        try:
            return self.execute(client, self.command("probe", ["--candidate", self.candidate]))
        finally:
            if fresh:
                client.close()

    def cli(self, command: str, confirm: bool = False) -> str:
        self.assert_lock()
        output = self.cli_callback(command, confirm)
        if re.search(
            r"(?im)^(?:\s*(?:error:|invalid command|configuration path.*not valid|"
            r"commit failed|failed to|load failed|save failed|syntax error|"
            r"another confirm is pending|no confirm pending|cannot |set failed))",
            output,
        ):
            raise GuardError("CLI operation was rejected")
        return output

    def backup(self, snapshot: dict) -> None:
        write(self.output / "running.config.boot", snapshot["running_text"])
        write(self.output / "saved.config.boot", snapshot["saved_text"])

    def diff(self, text: str) -> None:
        write(self.output / "candidate.diff", text)

    def ping(self, targets: list[str]) -> None:
        self.assert_lock()
        # One command per target bounds individual command latency.
        for target in targets:
            self.execute(self.client, self.command("ping", ["--targets", target]))

    def cleanup(self) -> None:
        failed = False
        try:
            if self.sftp and self.created:
                for name in ("config.boot", "probe.py"):
                    try:
                        self.sftp.remove(self.remote + "/" + name)
                    except FileNotFoundError:
                        continue
                    except OSError:
                        failed = True
                try:
                    self.sftp.rmdir(self.remote)
                except OSError:
                    failed = True
        finally:
            if self.lock_channel:
                self.lock_channel.close()
            if self.sftp:
                self.sftp.close()
            if self.client:
                self.client.close()
        if failed:
            raise GuardError("Remote temporary files could not be removed")
