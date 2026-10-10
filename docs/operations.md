# 日々の運用

## 操作を選ぶ

| 操作 | すること | 実機への接続 |
|---|---|---|
| `./vyos list` | 機器名と編集ファイルを表示 | なし |
| `./vyos doctor` | OS・Python・依存関係の有無を確認 | なし |
| `./vyos check [機器名]` | 接続情報と設定の構造を確認。省略すると全機器 | なし |
| `./vyos plan 機器名` | load・compare後、候補を破棄 | あり |
| `./vyos diff 機器名` | 直近の成功したplanの差分を表示 | なし |
| `./vyos apply 機器名` | バックアップ・全体置換・検証・保存 | あり |
| `./vyos backup 機器名` | 稼働設定・保存設定を保存 | あり |
| `./vyos save 機器名` | 確定済みで保存に失敗した設定を検証し保存 | あり |

doctorはSSH到達性や実機対応を確認しません。planとapplyは候補設定を操作します。他の作業者の設定作業と重ねないでください。

## 二台目を増やす

`devices/router02/config.boot` を用意し、Inventoryに `router02` を追加します。設定は実機から取り込み、管理接続を維持します。

```bash
./vyos check
./vyos plan router02
./vyos diff router02
./vyos apply router02
```

CLIの投入対象は一回につき一台、完全一致の名前です。`all` やワイルドカードで意図せず全機器へ投入することはありません。特殊なInventoryは `--inventory path/to/hosts.yml` で指定できます。

## 保存されたファイル

結果に表示される保存先に、実施した操作に応じて以下を残します。

| ファイル | 内容 |
|---|---|
| `config.boot` | 投入用の設定 |
| `running.config.boot` | 作業前の稼働設定 |
| `saved.config.boot` | 作業前の保存設定 |
| `candidate.diff` | 実機が返した差分 |
| `result.json` | 成否、フェーズ、復旧状態。設定本文は含めない |

既定の保存先は `${XDG_STATE_HOME:-$HOME/.local/state}/vyos-iac`。変更する場合は `VYOS_IAC_ARTIFACT_ROOT` に絶対パスを指定し、その親ディレクトリを先に作ります。本人所有・0700のディレクトリと0600のファイルを強制できるファイルシステムが必要です。シンボリックリンクは拒否します。

成果物は自動削除しません。変更管理に必要な期間を決め、暗号化した保管先への退避や削除を運用で行います。CIからのアップロードは行いません。

## AI・自動処理から使う

```bash
./vyos list --json
./vyos check router01 --json
./vyos plan router01 --json --private-key "$HOME/.ssh/vyos"
```

正常に受理された操作は標準出力にJSONを一つ返します。`schema_version`、`operation`、`ok`、`devices` が入口です。各機器には `code`、`summary`、`next_step`、必要に応じて `phase`、`state`、`config_path`、`artifact_path` を返します。処理分岐には日本語文ではなくcode／stateを使います。

終了コードは0が成功、1がチェック・操作失敗、2が入力・環境エラー、130が中断です。引数の書き間違いや `--help` は通常のCLIヘルプ表示です。対話式のVault入力とJSONは併用できません。

`diff --json` は明示的に設定差分を含みます。秘密を含む可能性があるため、AIへの入力や共有ログへ自動転送しないでください。

## Ansibleを直接使う

CLIは同じPlaybookを呼び出す薄い入口です。直接操作もできます。activateしたLinuxの仮想環境を使います。

```bash
export ANSIBLE_CONFIG="$PWD/src/ansible.cfg"
ansible-playbook src/playbooks/render.yml --limit router01
ansible-playbook src/playbooks/plan.yml --limit router01
ansible-playbook src/playbooks/apply.yml --limit router01
ansible-playbook src/playbooks/backup.yml --limit router01
```

apply／saveには明示的な `--limit` が必要です。Playbookは一台ずつ処理し、失敗時は後続を止めます。`--check` はローカルrenderのみ対応です。

## 投入の前提

管理IP、管理インターフェース全体、SSH設定全体、投入用ユーザー全体を実機と一致させます。変更するとcommit前に停止します。接続先の系列一致、未保存変更なし、競合セッションなし、未確定commitなし、reload復旧対応、commit履歴二件以上も確認します。

排他ロックは同じ仕組みを使う投入間に作用します。手動作業との完全な原子性はありません。メンテナンス時間を共有してください。実機の対応範囲と受入確認は [初期設定](bootstrap.md) と [受入テスト](../src/tests/integration/README.md) に記載しています。
