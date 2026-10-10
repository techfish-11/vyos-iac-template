"""One vocabulary for people, Ansible, and JSON consumers. No raw device errors."""

ERRORS = {
    "Cannot acquire the device lock": (
        "lock_conflict",
        "機器の作業ロックを取得できませんでした。",
        "別の投入の終了を確認してください。SSH接続と/configの権限も確認できます。",
    ),
    "Device lock was lost": (
        "lock_lost",
        "機器の作業ロックとの接続が失われました。",
        "実機の状態を確認してから再実行してください。docs/recovery.mdを参照できます。",
    ),
    "CLI operation was rejected": (
        "config_rejected",
        "VyOSが操作を受け付けませんでした。",
        "config.bootの構文と対象ビルドを確認してください。状態はdocs/recovery.mdを参照。",
    ),
    "Remote validation or capability check failed": (
        "remote_check_failed",
        "実機の構成取得または能力検査を完了できませんでした。",
        "docs/bootstrap.mdで対応条件と実行ユーザーの権限を確認してください。",
    ),
    "Required management configuration is missing": (
        "management_missing",
        "管理接続または復旧に必要な設定が不足しています。",
        "表示された設定パスを実機とconfig.bootで確認してください。docs/bootstrap.mdに例があります。",
    ),
    "At least two commit revisions are required for rollback": (
        "history_required",
        "自動復旧に必要なcommit履歴を保持できません。",
        "実機とconfig.bootのsystem config-management commit-revisionsを2以上にしてください。",
    ),
    "Save recovery requires the reviewed running configuration": (
        "save_source_mismatch",
        "稼働設定とconfig.bootが一致しないため、保存を止めました。",
        "実機の稼働設定とGitの設定をレビューしてください。docs/recovery.mdを参照できます。",
    ),
    "Running configuration changed during planning": (
        "concurrent_change",
        "確認中に実機の稼働設定が変わりました。",
        "他の設定作業が終了してから、planで差分を取り直してください。",
    ),
    "Configuration changed during save recovery": (
        "concurrent_change",
        "保存復旧中に実機の稼働設定が変わりました。",
        "他の設定作業と実機の状態を確認してください。docs/recovery.mdを参照できます。",
    ),
    "Unexpected configuration command output": (
        "unsupported_output",
        "実機の設定出力を安全に解釈できませんでした。",
        "対象ビルドのCLI出力と構成取得処理を受入環境で確認してください。",
    ),
    "Empty configuration command output": (
        "unsupported_output",
        "実機の設定出力を取得できませんでした。",
        "対象ビルドと実行ユーザーの権限を受入環境で確認してください。",
    ),
    "Device version does not match inventory": (
        "version_mismatch",
        "実機とInventoryのVyOSバージョンが違います。",
        "実機でshow versionを確認し、inventory/hosts.ymlのvyos_versionを合わせてください。",
    ),
    "Management connection configuration must remain unchanged": (
        "management_changed",
        "管理接続に使う設定が変わるため、投入を止めました。",
        "config.bootの管理インターフェース、SSH、投入用ユーザーを実機と一致させてください。",
    ),
    "Running configuration has unsaved changes": (
        "unsaved_changes",
        "実機に未保存の変更があります。",
        "実機のcompare savedで未保存差分を確認し、変更の扱いを決めてから再実行してください。",
    ),
    "Unexpected commit-confirm timer state": (
        "pending_commit",
        "commit-confirmの状態を確認できませんでした。",
        "別の投入が進行中でないか確認してください。復旧待ちならconfirmやsaveをしないでください。",
    ),
    "Conflicting or unrecognised configuration session": (
        "session_conflict",
        "別の設定セッションを検出しました。",
        "他の作業者の終了を確認してから再実行してください。セッションを強制終了しないでください。",
    ),
    "This build does not support soft commit-confirm rollback": (
        "reload_unsupported",
        "このビルドでは再起動なしの自動復旧を利用できません。",
        "docs/bootstrap.mdで対応条件を確認し、reload対応ビルドを検証してください。",
    ),
    "commit-confirm action reload is required": (
        "reload_required",
        "commit-confirmの復旧方式をreloadに設定してください。",
        "docs/bootstrap.mdの初期設定を実機とconfig.bootの両方で確認してください。",
    ),
    "Loaded candidate does not match the generated file": (
        "candidate_mismatch",
        "読み込まれた候補設定がファイルと一致しません。",
        "設定は未適用です。対象バージョンの構文と、自動補完・移行された設定を受入環境で確認してください。",
    ),
}


def describe(result: dict, mode: str, host: str) -> dict:
    failed = result.get("operation_failed", result.get("failed", False))
    reason = result.get("reason", "")
    state = result.get("state", "unchanged")
    if failed:
        if state in {"applied_not_saved", "confirm_outcome_unknown"}:
            message = (
                "persistence_incomplete",
                "設定の確定または保存が完了していません。",
                "docs/recovery.mdで実機の状態を確認してください。"
                f"確定済みなら ./vyos save {host} で保存を復旧できます。",
            )
        elif state in {"awaiting_rollback", "commit_outcome_unknown"}:
            message = (
                "rollback_pending",
                "仮適用の検証が完了しませんでした。",
                "confirmやsaveをせず、自動復旧の期限後に接続と設定を確認してください。docs/recovery.mdを参照できます。",
            )
        elif result.get("session_cleanup_failed") or result.get("artifact_cleanup_failed"):
            message = (
                "cleanup_incomplete",
                "後片付けを完了できませんでした。",
                "設定の状態はstateで確認してください。docs/recovery.mdの後処理を実施してください。",
            )
        elif reason in ERRORS:
            message = ERRORS[reason]
        elif reason and result.get("phase", "validation") == "validation":
            message = (
                "invalid_input",
                reason,
                "示されたファイルを修正し、checkをやり直してください。",
            )
        else:
            phase = result.get("phase", "validation")
            next_step = {
                "lock": "SSH鍵、known_hosts、/configへの書き込み権限を確認してください。",
                "load": "config.bootの構文が対象ビルドに対応しているか確認してください。",
            }.get(
                phase,
                "./vyos doctor を実行してください。実機の確認手順はdocs/recovery.mdにあります。",
            )
            message = ("operation_failed", "処理を完了できませんでした。", next_step)
    elif mode == "render":
        message = (
            "checked",
            "手元の設定の構造を確認しました。実機には接続していません。",
            f"内容をレビューしたら ./vyos plan {host} で実機との差分を確認できます。",
        )
    elif mode == "plan":
        message = (
            "changes_found" if result.get("would_change") else "no_changes",
            "実機との差分があります。まだ適用していません。"
            if result.get("would_change")
            else "実機との差分はありません。",
            (
                f"./vyos diff {host} で差分を確認できます。"
                f"変更する場合は ./vyos apply {host} を実行してください。"
            )
            if result.get("would_change")
            else "追加の投入は不要です。",
        )
    elif mode == "backup":
        message = (
            "backed_up",
            "稼働設定と保存設定をバックアップしました。",
            "保存先を確認してください。",
        )
    elif state == "saved":
        message = (
            "saved",
            "設定の検証と保存が完了しました。",
            "実行記録は保存先のresult.jsonにあります。",
        )
    else:
        message = ("no_changes", "設定の変更はありません。", "commitとsaveは実行していません。")
    return dict(zip(("code", "summary", "next_step"), message, strict=True))
