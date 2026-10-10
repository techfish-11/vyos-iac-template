from pathlib import Path

import pytest

from vyos_iac import config
from vyos_iac.config import ValidationError, check_structure, quote, render, validate


@pytest.mark.parametrize("series", ["1.4", "1.5"])
def test_native_config_is_read_without_rewriting(device, series):
    device.update(version=series, source=f"examples/{series}/config.boot")
    assert render(device) == Path(device["source"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("value", ['a"b', "a\\b", "a\nb", "a\x00b", "a}b", "a{b", ""])
def test_secret_injection_is_rejected(value):
    with pytest.raises(ValidationError):
        quote(value)


@pytest.mark.parametrize("text,line", [
    ('system {\n host-name "private-secret\n}', 2),
    ("system {\n login {\n }\n", 1),
    ("system {}\n}", 2),
    ("/* unclosed", 1),
])
def test_error_reports_location_without_private_values(text, line):
    with pytest.raises(ValidationError) as error:
        check_structure(text, "devices/router01/config.boot")
    assert f"config.boot:{line}" in str(error.value)
    assert "private-secret" not in str(error.value)


def test_comments_and_quoted_braces_are_native():
    check_structure('/* { */ system {\n host-name "a}b" // }\n}\n')


@pytest.mark.parametrize("text", ["", "set system host-name router01", "system {\x00}",
                                 "system {\x7f}"])
def test_invalid_structure_rejected(text):
    with pytest.raises(ValidationError):
        check_structure(text)


@pytest.mark.parametrize("change", [
    lambda d: d.update(port=True),
    lambda d: d.update(port=0),
    lambda d: d.update(host="-oProxyCommand=bad"),
    lambda d: d.update(source="../../config.boot"),
    lambda d: d.update(healthcheck_targets=[]),
    lambda d: d.update(healthcheck_targets=["fe80::1%bad"]),
    lambda d: d.update(config={"interfaces": []}),
])
def test_invalid_metadata_rejected(device, change):
    change(device)
    with pytest.raises(ValidationError) as error:
        validate(device)
    assert "ProxyCommand" not in str(error.value)


@pytest.fixture
def secret_source(tmp_path, monkeypatch, device):
    original = config.ROOT / "src/schemas/device.json"
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / "src/schemas").mkdir(parents=True)
    (tmp_path / "src/schemas/device.json").write_bytes(original.read_bytes())
    device["source"] = "config.boot"
    return tmp_path


def test_secrets_only_template(device, secret_source):
    (secret_source / "config.boot.j2").write_text(
        'system {\n login { encrypted-password {{ secrets.hash | vyos_quote }} }\n}\n',
        encoding="utf-8",
    )
    device["secrets"] = {"hash": "$6$salt$private"}
    assert '"$6$salt$private"' in render(device)


def test_missing_secret_has_actionable_error(device, secret_source):
    (secret_source / "config.boot.j2").write_text(
        "system { value {{ secrets.missing | vyos_quote }} }", encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="secrets.vault.yml"):
        render(device)


@pytest.mark.parametrize("text", [
    "{% for x in interfaces %}system {}{% endfor %}",
    "system { host-name {{ config.hostname }} }",
    "system { key {{ secrets.key.__class__ }} }",
])
def test_feature_generation_and_template_code_are_rejected(device, secret_source, text):
    (secret_source / "config.boot.j2").write_text(text, encoding="utf-8")
    with pytest.raises(ValidationError):
        render(device)


def test_ambiguous_configuration_is_rejected(device, secret_source):
    (secret_source / "config.boot").write_text("system {}")
    (secret_source / "config.boot.j2").write_text("system {}")
    with pytest.raises(ValidationError, match="どちらか一方"):
        render(device)
