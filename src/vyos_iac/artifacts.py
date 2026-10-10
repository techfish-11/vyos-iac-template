"""Private controller artifacts. Reject symlinks and never overwrite run artifacts."""

import json
import os
import re
import stat
import uuid
from pathlib import Path

from vyos_iac.config import ValidationError


def directory(host: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", host):
        raise ValidationError("Inventory hostname is not a safe artifact identifier")
    override = os.environ.get("VYOS_IAC_ARTIFACT_ROOT")
    state_home = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    root = Path(override) if override else state_home / "vyos-iac"
    if not root.is_absolute():
        raise ValidationError("Artifact root must be an absolute path")
    for ancestor in [root, *root.parents]:
        if ancestor.is_symlink():
            raise ValidationError("Artifact path must not contain symlinks")
    if not override:
        root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not root.parent.is_dir():
        raise ValidationError("Artifact root parent must already exist")
    for path in [root, root / host]:
        if path.is_symlink():
            raise ValidationError("Artifact directories must not be symlinks")
        path.mkdir(mode=0o700, exist_ok=True)
        if not path.is_dir():
            raise ValidationError("Artifact path is not a directory")
        if os.name == "posix" and path.stat().st_uid != os.getuid():
            raise ValidationError("Artifact directory must belong to the controller user")
        path.chmod(0o700)
        if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) != 0o700:
            raise ValidationError("Artifact filesystem cannot enforce private permissions")
    run = root / host / uuid.uuid4().hex
    run.mkdir(mode=0o700)
    return run


def write(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        if os.name == "posix" and stat.S_IMODE(os.fstat(stream.fileno()).st_mode) != 0o600:
            raise ValidationError("Artifact filesystem cannot enforce private file permissions")
        stream.write(content)


def report(path: Path, result: dict) -> None:
    write(path / "result.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
