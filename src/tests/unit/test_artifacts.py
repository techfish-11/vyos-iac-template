from pathlib import Path

import pytest

from vyos_iac.artifacts import directory, write
from vyos_iac.config import ValidationError


def test_artifact_hostname_cannot_escape():
    with pytest.raises(ValidationError):
        directory("../../outside")


def test_existing_artifact_cannot_be_overwritten(tmp_path):
    path = tmp_path / "config.boot"
    write(path, "original")
    with pytest.raises(FileExistsError):
        write(path, "replacement")
    assert path.read_text() == "original"


def test_symlink_artifact_cannot_be_overwritten(tmp_path):
    destination = tmp_path / "real"
    destination.write_text("private")
    link = tmp_path / "link"
    try:
        Path(link).symlink_to(destination)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this host")
    with pytest.raises(FileExistsError):
        write(link, "replacement")
    assert destination.read_text() == "private"


def test_artifact_root_override_is_private(tmp_path, monkeypatch):
    root = tmp_path / "private-artifacts"
    monkeypatch.setenv("VYOS_IAC_ARTIFACT_ROOT", str(root))
    path = directory("router01")
    assert path.parent == root / "router01"


def test_relative_artifact_root_is_rejected(monkeypatch):
    monkeypatch.setenv("VYOS_IAC_ARTIFACT_ROOT", "relative")
    with pytest.raises(ValidationError):
        directory("router01")


def test_default_state_directory_is_created_without_environment_setup(tmp_path, monkeypatch):
    monkeypatch.delenv("VYOS_IAC_ARTIFACT_ROOT", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "new/state"))
    path = directory("router01")
    assert path.parent == tmp_path / "new/state/vyos-iac/router01"
