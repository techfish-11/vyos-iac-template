import pytest

from vyos_iac.messages import describe


@pytest.mark.parametrize("state,code", [
    ("awaiting_rollback", "rollback_pending"),
    ("commit_outcome_unknown", "rollback_pending"),
    ("applied_not_saved", "persistence_incomplete"),
    ("confirm_outcome_unknown", "persistence_incomplete"),
])
def test_recovery_state_takes_priority_over_input_error(state, code):
    result = describe({"failed": True, "state": state, "reason": "unknown"}, "apply", "r1")
    assert result["code"] == code
    assert "docs/recovery.md" in result["next_step"]


def test_management_error_has_next_action():
    result = describe({
        "failed": True, "reason": "Management connection configuration must remain unchanged",
    }, "apply", "router01")
    assert result["code"] == "management_changed"
    assert "config.boot" in result["next_step"]


def test_raw_transport_error_is_never_explained():
    result = describe({"failed": True, "msg": "private-value", "phase": "lock"}, "plan", "r1")
    assert "private-value" not in str(result)
    assert result["next_step"]
