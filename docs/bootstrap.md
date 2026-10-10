# 初回投入前の設定

管理接続がない機器は、コンソールから設定します。以下のIP、鍵名、公開鍵、インターフェースは実環境の値へ置き換えます。SSH秘密鍵は機器にもGitにも置きません。

```text
configure
set interfaces ethernet eth0 address '192.0.2.1/24'
set interfaces ethernet eth0 description 'Management'
set system login user automation authentication public-keys operator type 'ssh-ed25519'
set system login user automation authentication public-keys operator key '<公開鍵のbase64部分>'
set service ssh port '22'
set service ssh disable-password-authentication
set system config-management commit-revisions '100'
set system config-management commit-confirm action 'reload'
commit
save
exit
```

既存のDHCP設定、SSH追加設定、ユーザーのパスワードハッシュ、インターフェースの`hw-id`も含め、実機の設定を`devices/router01/config.boot`へそのまま取り込みます。管理インターフェース全体と投入用ユーザー全体は一致必須です。独自スキーマの拡張は不要です。秘密値は[Vaultへ分離](secrets.md)し、接続維持に必要な属性を削除して合わせないでください。

通常のadminユーザーが`/config`に書き込み可能であることを確認します。自動投入の排他ロックは`/config/.vyos-iac.lock`を使用します。同じ投入ユーザーを全実行者で使用し、ロックファイルの所有者が違う場合はコンソールで確認して調整してください。

VyOSコンソールでホスト鍵のfingerprintを取得します。

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

実行ホストでは候補の公開鍵を取得し、コンソールで確認したfingerprintと照合してから登録します。

```bash
umask 077
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keyscan -t ed25519 192.0.2.1 > /tmp/vyos-host-key
ssh-keygen -lf /tmp/vyos-host-key
# コンソールで確認したfingerprintと一致する場合のみ登録する。
cat /tmp/vyos-host-key >> ~/.ssh/known_hosts
chmod 600 ~/.ssh/known_hosts
rm /tmp/vyos-host-key
ssh automation@192.0.2.1
```

1.4／1.5でもreload復旧がないビルドがあります。設定コマンドの存在に加え、受入環境で通信を遮断し、実際に再起動なしで以前の設定へ戻ることを確認してください。投入処理は能力検査に通らない実機を拒否します。現在の構成取得処理はunionfsを使う設定バックエンドを前提とします。別のバックエンドのビルドは受入検証と実装対応が必要です。
