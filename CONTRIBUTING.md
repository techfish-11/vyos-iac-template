# 開発する

利用者の入口は `./vyos`、設定の入口は `devices/<機器>/config.boot` です。新機能を増やす前に、利用者が新しい独自形式を覚えずに済むか確認してください。

Linux / WSL2でセットアップした環境から、次を実行します。

```bash
. src/.venv/bin/activate
bash src/scripts/validate.sh
```

Windows用の.venvと併用する場合は `. src/.venv-linux/bin/activate`。単体テスト、Python lint、五つのPlaybookの構文検査、Ansible lint、両系列のローカル設定確認を実行します。実機へは接続しません。依存関係とCollectionは事前にsetupで用意します。

| 変更したいもの | 主な場所 |
|---|---|
| コマンド・JSON・対象選択 | `src/vyos_iac/cli.py` |
| ネイティブ設定読込・秘密の引用 | `src/vyos_iac/config.py` |
| 日本語の説明・次の操作・code | `src/vyos_iac/messages.py` |
| 入力する接続情報の形式 | `src/schemas/device.json` |
| 投入・復旧の状態遷移 | `src/vyos_iac/transaction.py` |
| SSH・ロック・ファイル転送 | `src/vyos_iac/transport.py` |
| 実機の構成取得 | `src/vyos_iac/remote_probe.py` |
| Ansibleとの接続 | `src/plugins/action/vyos_iac.py` |
| オフライン回帰テスト | `src/tests/unit/` |
| 実機受入・互換性表 | `src/tests/integration/README.md` |

設定本文の正しさはVyOS自身が判定します。オフラインの括弧チェックをVyOS構文パーサーと呼ばないでください。投入処理を変更した場合は、commit前・仮適用後・確定後・保存後の失敗と、応答が失われた場合をテストします。

CIは秘密情報と実機を使いません。成果物もアップロードしません。実機受入は別途必要です。
