# 書いた分だけ、VyOSがわかる

設定ファイルの階層と、VyOSの `set` コマンドの単語の並びは対応します。このリポジトリ独自のネットワーク設定モデルを覚える必要はありません。

例えば、次のconfig.bootは「203.0.113.0/24へは192.0.2.254を経由する」という静的ルートです。

```text
protocols {
    static {
        route 203.0.113.0/24 {
            next-hop 192.0.2.254 {
            }
        }
    }
}
```

VyOSのconfigureモードで同じ設定を書くと、こうなります。

```text
set protocols static route 203.0.113.0/24 next-hop 192.0.2.254
```

外側から内側へ読むと、同じ順番になっています。`show configuration commands` で実機設定をset形式でも確認できます。

| config.bootの入口 | CLIで書くときの入口 | 内容 |
|---|---|---|
| `interfaces → ethernet → eth1` | `set interfaces ethernet eth1 ...` | アドレス、説明等 |
| `protocols → static → route` | `set protocols static route ...` | 静的ルート |
| `service → ssh` | `set service ssh ...` | SSH |
| `service → ntp` | `set service ntp ...` | NTP |
| `system → name-server` | `set system name-server ...` | DNS |
| `system → login → user` | `set system login user ...` | 管理ユーザー |

試すときは、既存の `protocols.static` の中に上のrouteを追加します。同じトップレベルブロックを重複して追記する必要はありません。

```bash
./vyos check router01
./vyos plan router01
./vyos diff router01
```

ファイルからrouteを消すと、次のplanでは削除差分になります。applyはファイル全体へ置き換えるためです。変更内容を読んでから適用します。

オフラインのcheckが成功しても、コマンドの存在や値の妥当性は保証しません。系列ごとの例は [1.4](../examples/1.4/config.boot) と [1.5](../examples/1.5/config.boot)、構文は [VyOS公式ドキュメント](https://docs.vyos.io/en/1.4/cli.html) で確認できます。

Firewall、NAT、BGP等を追加する場合も、VyOSの構文を直接書けます。独自YAML用のスキーマや生成コードを追加する必要はありません。
