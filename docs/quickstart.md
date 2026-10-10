# 最初の一台

まずはサンプルを確認し、次に実機の設定を取り込みます。最初から秘密情報や実機接続は必要ありません。

## 1. 道具を準備する

Linux / WSL2のターミナルで、リポジトリのルートから実行します。Python 3.12以上が必要です。Ubuntuで仮想環境を作れない場合は `sudo apt install python3-venv` で準備します。

```bash
bash vyos setup
./vyos doctor
./vyos list
./vyos check router01
```

`setup` は`src/.venv`へ専用のPython環境と固定バージョンの依存関係を用意します。以降、activateや環境変数の手動設定は不要です。Windows用の環境と併用する場合は`src/.venv-linux`を使います。

`list` に機器名と編集するファイルが表示されます。`check` は接続情報、UTF-8、括弧・引用符・コメントの閉じ忘れを確認します。**IPやコマンドの意味を含む、VyOS固有の正しさは実機のload／commitで検証します。**

## 2. 実機の設定を取り込む

既存機器では、実機の `show configuration` で表示される階層形式の設定を `devices/router01/config.boot` に保存します。プロンプト・ページャーの表示は入れません。コンソールから `/config/config.boot` を安全に取得しても構いませんが、保存設定と稼働設定が一致していることを確認してください。

このファイルは設定全体です。既存のFirewall、NAT、ユーザーなど、残すものをすべて含めます。サンプルをそのまま既存機器へ投入しないでください。

管理接続がまだない場合は [初期設定](bootstrap.md) を先に実施します。既存の設定にパスワードハッシュなどが含まれる場合は、Gitに追加する前に [秘密情報の分離](secrets.md) を行います。

## 3. 接続先を登録する

[inventory/hosts.yml](../inventory/hosts.yml) のrouter01を編集します。

```yaml
all:
  children:
    vyos:
      hosts:
        router01:
          ansible_host: 192.0.2.1
          vyos_version: "1.4"
          vyos_management_interface: eth0
          vyos_healthcheck_targets:
            - 192.0.2.254
```

| 項目 | 意味 |
|---|---|
| `router01` | 操作する機器の名前。`devices/router01/config.boot` に対応 |
| `ansible_host` | SSH接続先の管理IP |
| `vyos_version` | 実機の系列。`"1.4"` または `"1.5"` |
| `vyos_management_interface` | 接続に使うethernetインターフェース |
| `vyos_healthcheck_targets` | 適用後に**VyOSから**pingするIP。到達が必要 |

共通のSSHユーザーは `automation`、ポートは22です。異なる場合だけ、同じ機器の下に `ansible_user` と `ansible_port` を追記します。公開鍵、SSH設定、管理インターフェース全体を実機と一致させてください。

鍵をSSH agentへ読み込み、検証済みのホスト鍵を `~/.ssh/known_hosts` に登録します。登録方法は [初期設定](bootstrap.md) にあります。秘密鍵を指定する場合は各操作に `--private-key /Git管理外のパス` を付けます。

## 4. 変更を確かめる

```bash
./vyos check router01
./vyos plan router01
./vyos diff router01
```

`plan` は実機の設定セッションで候補をloadし、差分を取得して破棄します。稼働設定・保存設定は変えません。`diff` は直近の成功したplanの記録です。秘密情報を含む可能性があるため、共有ログへ貼り付けないでください。

差分の追加・変更に加えて、**削除される設定**も読みます。管理接続の変更や未保存の変更がある場合は、理由と次の操作が表示されます。

## 5. 適用する

```bash
./vyos apply router01
```

バックアップ後、10分の自動復旧タイマー付きで仮適用します。新しいSSH接続、設定の一致、指定先へのpingがすべて成功したらconfirmし、saveします。途中で失敗したら [表示された状態に応じて復旧](recovery.md) します。

生成設定・バックアップ・差分は、既定で `~/.local/state/vyos-iac/<機器>/<実行ID>/` に保存します。結果にも保存先が表示されます。WSLでもLinux側へ保存するため、Windows側のリポジトリに秘密の成果物を置かずに済みます。
