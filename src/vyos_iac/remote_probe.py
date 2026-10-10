"""Transferred helper: uses only the standard library and VyOS' installed libraries.

No configuration mutations here. JSON stdout can contain secrets: never log it.
"""

import argparse
import fcntl
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return sorted((normalize(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def execute(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=True)
    return result.stdout


def lock():
    # A stable file is never unlinked, preventing two processes locking different inodes.
    fd = os.open("/config/.vyos-iac.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode):
            raise RuntimeError("Unsafe lock file")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print("LOCKED", flush=True)
        # SSH channel EOF or process termination releases the kernel lock.
        sys.stdin.buffer.read()
    finally:
        os.close(fd)


def probe(candidate):
    from vyos.config import Config
    from vyos.config_mgmt import ConfigMgmt
    from vyos.configtree import ConfigTree

    version_text = execute(["/opt/vyatta/bin/vyatta-op-cmd-wrapper", "show", "version"])
    match = re.search(r"Version:\s+VyOS\s+(\S+)", version_text)
    series = re.match(r"(1\.[45])(?:[.\-]|$)", match.group(1)) if match else None
    if not series:
        raise RuntimeError("Unsupported version output")
    timer = subprocess.run(
        ["systemctl", "is-active", "commit-confirm.timer"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if timer.returncode not in (0, 3) or timer.stdout.strip() not in ("active", "inactive"):
        raise RuntimeError("Cannot establish timer state")
    # Refuse unknown backends rather than guessing where sessions live.
    root = Path("/opt/vyatta/config/tmp")
    if not root.is_dir():
        raise RuntimeError("Unsupported session backend")
    sessions = 0
    for directory in root.glob("new_config_*"):
        sid = directory.name.removeprefix("new_config_")
        if not sid.isdecimal():
            raise RuntimeError("Unrecognised session identifier")
        if Path("/proc", sid).exists():
            sessions += 1
    running_tree = Config()._running_config
    running_text = running_tree.to_string()
    saved_text = Path("/config/config.boot").read_text()
    candidate_text = Path(candidate).read_text()
    candidate_tree = ConfigTree(candidate_text)
    return {
        "version": series.group(1),
        "build": match.group(1),
        "sessions": sessions,
        "pending": timer.stdout.strip() == "active",
        "reload_supported": hasattr(ConfigMgmt, "revert_soft"),
        "running": normalize(json.loads(running_tree.to_json())),
        "saved": normalize(json.loads(ConfigTree(saved_text).to_json())),
        "candidate": normalize(json.loads(candidate_tree.to_json())),
        "candidate_commands": candidate_tree.to_commands(),
        "running_text": running_text,
        "saved_text": saved_text,
        "running_commands": execute([
            "/opt/vyatta/bin/vyatta-op-cmd-wrapper", "show", "configuration", "commands",
        ]),
    }


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("Invalid helper arguments")


def main():
    parser = SafeArgumentParser()
    parser.add_argument("operation", choices=["lock", "probe", "ping"])
    parser.add_argument("--candidate")
    parser.add_argument("--targets", nargs="+")
    try:
        args = parser.parse_args()
        if args.operation == "lock":
            lock()
        elif args.operation == "probe":
            if not args.candidate:
                raise ValueError("Candidate path required")
            print(json.dumps(probe(args.candidate)))
        else:
            if not args.targets:
                raise ValueError("Health check targets required")
            for target in args.targets:
                address = str(ipaddress.ip_address(target))
                execute(["ping", "-n", "-c", "3", "-W", "2", address])
            print(json.dumps({"ok": True}))
    except Exception:
        print(json.dumps({"error": "Remote capability or validation check failed"}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
