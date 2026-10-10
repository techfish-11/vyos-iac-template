"""Read native VyOS configuration. YAML describes connections, never network features."""

from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined, Undefined, UndefinedError
from jinja2.sandbox import SandboxedEnvironment
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
MAX_CONFIG_BYTES = 1024 * 1024


class ValidationError(ValueError):
    """Safe diagnostic: locations and instructions, never configuration values."""


def quote(value: str) -> str:
    if isinstance(value, Undefined):
        raise UndefinedError("Missing secret")
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValidationError("秘密変数には空でない文字列を指定してください。")
    if any(ord(c) < 32 or ord(c) == 127 or c in '\\"{}' for c in value):
        raise ValidationError("秘密変数に改行・引用符など使用できない文字が含まれています。")
    return '"' + value + '"'


def source_path(source: str) -> Path:
    if not isinstance(source, str):
        raise ValidationError("設定ファイルのパスを指定してください。")
    path = (ROOT / source).resolve()
    if not path.is_relative_to(ROOT) or path.name not in {"config.boot", "config.boot.j2"}:
        raise ValidationError(
            "設定はリポジトリ内のconfig.bootまたはconfig.boot.j2に置いてください。"
        )
    if path.name == "config.boot":
        alternate = path.with_name("config.boot.j2")
        if path.is_file() and alternate.is_file():
            raise ValidationError(
                f"{source}: config.bootとconfig.boot.j2はどちらか一方にしてください。"
            )
        if not path.exists() and alternate.is_file():
            path = alternate.resolve()
            if not path.is_relative_to(ROOT):
                raise ValidationError("設定ファイルをリポジトリ内に置いてください。")
    if not path.is_file():
        raise ValidationError(
            f"{source}: ファイルがありません。設定ファイルの置き場所を確認してください。"
        )
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise ValidationError(f"{source}: 設定ファイルは1 MiB以下にしてください。")
    return path


def validate(data: dict[str, Any]) -> dict[str, Any]:
    schema = json.loads((ROOT / "src/schemas/device.json").read_text(encoding="utf-8"))
    error = next(iter(Draft202012Validator(schema).iter_errors(data)), None)
    if error:
        field = ".".join(str(p) for p in error.absolute_path) or "device"
        raise ValidationError(
            f"接続情報の{field}を確認してください。形式や必須項目が一致しません。"
        )
    try:
        for address in [data["host"], *data["healthcheck_targets"]]:
            if "%" in address:
                raise ValueError
            ipaddress.ip_address(address)
    except ValueError as exc:
        raise ValidationError(
            "接続先と疎通確認先には、ゾーンIDを含まないIPアドレスを指定してください。"
        ) from exc
    source_path(data["source"])
    return data


def check_structure(text: str, source: str = "config.boot") -> None:
    """Check delimiters, not VyOS' version-specific configuration semantics."""
    if not text.strip():
        raise ValidationError(f"{source}: 設定が空です。全体置換に使う設定を記入してください。")
    stack: list[int] = []
    line = 1
    quote_char = ""
    quote_line = 0
    comment = ""
    comment_line = 0
    escaped = False
    seen_block = False
    i = 0
    while i < len(text):
        char = text[i]
        pair = text[i : i + 2]
        if (ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127:
            raise ValidationError(f"{source}:{line}: 使用できない制御文字があります。")
        if comment == "line":
            if char == "\n":
                comment = ""
        elif comment == "block":
            if pair == "*/":
                comment = ""
                i += 1
        elif quote_char:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote_char:
                quote_char = ""
        elif pair in {"/*", "//"}:
            comment = "block" if pair == "/*" else "line"
            comment_line = line
            i += 1
        elif char in "\"'":
            quote_char, quote_line = char, line
        elif char == "{":
            seen_block = True
            stack.append(line)
        elif char == "}":
            if not stack:
                raise ValidationError(
                    f"{source}:{line}: 対応する開始括弧のない閉じ括弧があります。"
                )
            stack.pop()
        if char == "\n":
            line += 1
        i += 1
    if quote_char:
        raise ValidationError(f"{source}:{quote_line}: 引用符が閉じていません。")
    if comment == "block":
        raise ValidationError(f"{source}:{comment_line}: コメントを */ で閉じてください。")
    if stack:
        raise ValidationError(f"{source}:{stack[-1]}: この行で開いた括弧を閉じてください。")
    if not seen_block:
        raise ValidationError(
            f"{source}: VyOSの階層形式を使ってください。examples/を参照できます。"
        )


def render(data: dict[str, Any]) -> str:
    validate(data)
    path = source_path(data["source"])
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ValidationError(f"{data['source']}: UTF-8で保存し直してください。") from exc
    if path.name.endswith(".j2"):
        if "{%" in text or "{#" in text:
            raise ValidationError(
                "設定のループ生成は使いません。VyOSの設定をそのまま記入してください。"
            )
        expressions = re.findall(r"{{(.*?)}}", text, flags=re.DOTALL)
        pattern = r"\s*secrets\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\|\s*vyos_quote\s*"
        for expression in expressions:
            match = re.fullmatch(pattern, expression)
            if not match:
                raise ValidationError(
                    "秘密変数は {{ secrets.変数名 | vyos_quote }} の形式で使ってください。"
                )
            if match[1] not in data["secrets"]:
                raise ValidationError(
                    f"{data['source']}: secrets.{match[1]}が不足しています。"
                    "secrets.vault.ymlに定義してください。"
                )
        env = SandboxedEnvironment(
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )
        env.filters["vyos_quote"] = quote
        try:
            text = env.from_string(text).render(secrets=data["secrets"])
        except UndefinedError as exc:
            raise ValidationError(
                "秘密変数が不足しています。対応するsecrets.vault.ymlを確認してください。"
            ) from exc
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(
                "秘密変数の書き方を確認してください。docs/secrets.mdに例があります。"
            ) from exc
    elif "{{" in text or "{%" in text:
        raise ValidationError("秘密変数を使う場合はconfig.bootをconfig.boot.j2に変更してください。")
    if len(text.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ValidationError("秘密値を差し込んだ設定は1 MiB以下にしてください。")
    check_structure(text, data["source"])
    return text
