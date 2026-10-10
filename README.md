# VyOSの設定を、そのままGitで管理する

普段の作業で編集するのは [devices/router01/config.boot](devices/router01/config.boot) です。VyOSの `show configuration` と同じ階層形式なので、書いた内容がそのままVyOSの学習になります。接続先だけをAnsible Inventoryに置きます。

```bash
./vyos check router01   # 手元の構造を確認。実機には接続しません
./vyos plan router01    # 実機との差分を確認。適用せず候補を破棄します
./vyos diff router01    # 差分を読む
./vyos apply router01   # 検証しながら適用し、成功したら保存
```

**初めてなら [最初の一台](docs/quickstart.md) から。** Linux / WSL2、Python 3.12以上を使います。初回の準備は `bash vyos setup` です。サンプルのIP・公開鍵は例示用です。

設定は**全体置換**です。ファイルに残していない実機設定は削除対象になります。投入前に現在の設定を取り込み、`plan` の差分を確認してください。管理接続の変更は初版の対象外です。

| したいこと | 読む場所 |
|---|---|
| 一台を登録して動かす | [最初の一台](docs/quickstart.md) |
| VyOSの書き方を覚える | [CLIとconfig.bootの対応](docs/learning.md) |
| 管理IP・SSH・鍵を準備する | [初期設定](docs/bootstrap.md) |
| パスワード等を分離する | [秘密情報](docs/secrets.md) |
| 複数台・バックアップ・Ansibleを直接使う | [運用](docs/operations.md) |
| 失敗時の表示から次の行動を決める | [復旧](docs/recovery.md) |
| AIや開発者に変更を依頼する | [AGENTS.md](AGENTS.md) / [開発](CONTRIBUTING.md) |

操作の一覧は `./vyos --help`、環境の確認は `./vyos doctor`。AIやスクリプトには `./vyos check router01 --json` を使えます。通常の結果表示に設定本文・秘密値は含めません。`diff` は明示的に設定差分を表示します。

普段触る場所は`devices/`（設定）、`inventory/`（接続先）、`examples/`（設定例）、`docs/`（手順）です。内部実装・Playbook・テスト・依存関係は`src/`にまとめています。`.github/`はGitHub Actionsに必要な配置です。

1.4／1.5の設定例を [examples/](examples/) に置いています。**実機検証済みビルドはまだありません。** 採用するビルドは [受入テスト](src/tests/integration/README.md) で確認してから本番で使用してください。
