# 秘密が必要になったら

公開鍵だけの設定では、この手順は不要です。パスワードハッシュ、共有鍵など、Gitに平文で残せない値がある場合に使います。

## 秘密の値だけをVaultへ移す

1. `devices/router01/config.boot` を `config.boot.j2` に名前変更します。両方は残しません。
2. 秘密値を、次の形式の差し込みへ置き換えます。引用符はフィルターが付けるので、自分では付けません。

```text
encrypted-password {{ secrets.password_hash | vyos_quote }}
```

3. Ansible Vaultで、同じディレクトリに暗号化ファイルを作ります。

```bash
src/.venv/bin/ansible-vault create devices/router01/secrets.vault.yml
```

Windows用の.venvと併用している場合は `src/.venv-linux/bin/ansible-vault` を使います。開いたエディターに次の構造で実際の値を記入します。

```yaml
secrets:
  password_hash: "実機で使用するパスワードハッシュ"
```

Vaultには秘密値だけを入れます。インターフェースやルートをYAMLで定義することはありません。`.j2` でもVyOSの設定全体をそのまま書きます。ループ・条件分岐・秘密以外の式は受け付けません。

## いつもの操作に復号方法を付ける

```bash
./vyos check router01 --ask-vault-pass
./vyos plan router01 --ask-vault-pass
./vyos apply router01 --ask-vault-pass
```

`config.boot.j2` は自動的に見つかるため、Inventoryの変更は不要です。checkでもVaultを復号するため、この場合はAnsibleのローカルrenderを使います。実機へは接続しません。

AIやスクリプトには、Git管理外・本人だけが読める復号鍵ファイルを指定します。

```bash
./vyos check router01 --json --vault-password-file "$HOME/.config/vyos/vault-password"
```

暗号化した `secrets.vault.yml` はGit管理できます。SSH秘密鍵、復号鍵、平文の下書きは管理しません。復号した設定、バックアップ、差分にも秘密値が含まれるため、保存先を扱える人を制限します。復号鍵ファイルとSSH秘密鍵は0600にしてください。

`vyos_quote` は改行・引用符・バックスラッシュ・波括弧・制御文字を含む値を拒否します。拒否された秘密値をエラー出力に載せることはありません。必要な値がこの制限に収まらない場合は、対応形式を設計・テストしてから拡張してください。
