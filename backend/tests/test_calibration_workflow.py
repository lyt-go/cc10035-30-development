"""校准审批、版本冲突和告警留证的场景测试。"""
from __future__ import annotations

import pytest

from app.services.alarm_trigger import AlarmTriggerService
from app.services.calibration import workflow
from app.store import store


@pytest.fixture(autouse=True)
def reset_calibration_scenario():
    workflow.reset_scenario()
    yield
    workflow.reset_scenario()


def test_seed_has_strict_threshold_and_original_79_is_safe():
    rule = workflow.alarm_rule()
    assert rule["operator"] == ">"
    assert float(rule["阈值上限"]) == 80

    result = workflow.confirm_original_79()
    assert result["ok"] is True
    assert result["triggered"] is False
    assert result["result"]["raw_value"] == 79.0
    assert result["result"]["calibrated_value"] == 79.0
    assert result["result"]["coefficient_version"] == "CAL-COEF-V1"
    assert store.find("sample_reading", 9101)["status"] == "已确认"


def test_invalid_unit_row_is_rejected_without_blocking_offset_row():
    outcome = workflow.process_verification_payload({"batch_id": "CAL-BATCH-001"})

    assert outcome["accepted_count"] == 1
    assert outcome["rejected_count"] == 1
    valid = next(row for row in store.rows("calibration_verification") if row["检定行号"] == "CAL-VER-OFFSET2")
    invalid = next(row for row in store.rows("calibration_verification") if row["检定行号"] == "CAL-VER-BAD-UNIT")
    assert valid["status"] == "校验通过"
    assert invalid["status"] == "已退回"
    assert "单位不一致" in invalid["处理意见"]

    # 错单位行没有产生新版本，当前身份仍只有 V1 生效基线。
    versions = [
        row["系数版本"] for row in store.rows("calibration_coefficient")
        if row["identity_key"] == "DEVI-0001::PRB-A-0001"
    ]
    assert versions == ["CAL-COEF-V1"]


def test_invalid_numeric_row_is_rejected_and_keeps_current_coefficient():
    created = workflow.create_verification({
        "检定行号": "CAL-VER-BAD-NUMBER",
        "设备编号": "DEVI-0001",
        "探头实际身份": "PRB-A-0001",
        "标准单位": "℃",
        "检定单位": "℃",
        "乘数": "abc",
        "偏移": "2",
    })
    checked = workflow.validate_verification(created["row"]["检定行号"])
    assert checked["ok"] is False
    assert checked["row"]["status"] == "已退回"
    assert workflow.create_approval("CAL-VER-BAD-NUMBER")["ok"] is False


def test_approval_effect_conflicts_then_uses_same_v2_coefficients_and_traces():
    workflow.confirm_original_79()
    workflow.process_verification_payload({"batch_id": "CAL-BATCH-001"})
    created = workflow.create_approval("CAL-VER-OFFSET2")
    approval_id = created["approval"]["审批单号"]

    activated = workflow.activate_approval(approval_id)
    assert activated["ok"] is True
    assert activated["conflict"] is True

    detail = workflow.approval_detail(approval_id)
    assert detail["approval"]["status"] == "已生效"
    assert "待处理" in detail["approval"]["conflict_status"]
    assert [todo["status"] for todo in detail["todos"]] == ["已完成", "待处理"]
    # 生效到达后，告警服务已立即按同一 V2 版本给出可回查判定；人工确认后关闭待办。
    assert len(detail["alarm_results"]) == 1
    assert detail["alarm_results"][0]["calibrated_value"] == 81.0
    conflict_sample = next(row for row in store.rows("sample_reading") if row["采样单号"] == "SR-INFLIGHT-79")
    assert conflict_sample["version_conflict"] is True
    assert conflict_sample["pre_conflict_snapshot"]["coefficient_version"] == "CAL-COEF-V1"
    assert conflict_sample["pre_conflict_snapshot"]["calibrated_value"] == 79.0
    assert conflict_sample["coefficient_version"] == "CAL-COEF-V2"

    resolved = workflow.resolve_conflict(approval_id)
    assert resolved["ok"] is True
    detail = workflow.approval_detail(approval_id)

    assert all(todo["status"] == "已完成" for todo in detail["todos"])
    assert len(detail["alarm_results"]) == 1
    result = detail["alarm_results"][0]
    assert result["raw_value"] == 79.0
    assert result["multiplier"] == 1.0
    assert result["offset"] == 2.0
    assert result["calibrated_value"] == 81.0
    assert result["threshold"] == 80.0
    assert result["operator"] == ">"
    assert result["triggered"] is True
    assert result["coefficient_version"] == "CAL-COEF-V2"
    assert result["coefficient_fields"] == {
        "multiplier_from_same_version": "CAL-COEF-V2",
        "offset_from_same_version": "CAL-COEF-V2",
    }

    # 幂等回查不应重复生成告警结果。
    again = workflow.resolve_conflict(approval_id)
    assert again.get("idempotent") is True
    assert len(workflow.approval_detail(approval_id)["alarm_results"]) == 1


def test_alarm_service_after_effectiveness_judges_time_qualified_79_as_81():
    workflow.process_verification_payload({"batch_id": "CAL-BATCH-001"})
    workflow.create_approval("CAL-VER-OFFSET2")
    workflow.activate_approval("CAL-APR-0001")

    alarm = AlarmTriggerService().evaluate_threshold("TS_P-CAL-80", 79)
    assert alarm["calibration"]["coefficient_version"] == "CAL-COEF-V2"
    assert alarm["calibrated_value"] == 81.0
    assert alarm["triggered_count"] == 1

    # 严格大于：校准后恰好 80 的原始值 78 不触发。
    boundary = AlarmTriggerService().evaluate_threshold("TS_P-CAL-80", 78)
    assert boundary["calibrated_value"] == 80.0
    assert boundary["triggered_count"] == 0


def test_same_name_probe_is_isolated_by_device_and_actual_identity():
    workflow.process_verification_payload({"batch_id": "CAL-BATCH-001"})
    workflow.create_approval("CAL-VER-OFFSET2")
    workflow.activate_approval("CAL-APR-0001")

    other = AlarmTriggerService().calibration_context("TS_P-CAL-80-B", 79)
    assert other["identity_key"] == "DEVI-0002::PRB-B-0002"
    assert other["coefficient_version"] == "CAL-COEF-OTHER-V1"
    assert other["offset"] == 0.0
    assert other["calibrated_value"] == 79.0


def test_confirmed_historical_result_remains_on_v1_after_new_version():
    confirmed = workflow.confirm_original_79()["result"]
    workflow.process_verification_payload({"batch_id": "CAL-BATCH-001"})
    workflow.create_approval("CAL-VER-OFFSET2")
    workflow.activate_approval("CAL-APR-0001")

    sample = workflow.find_row("sample_reading", "SR-HIST-79")
    assert sample["status"] == "已确认"
    assert sample["coefficient_version"] == "CAL-COEF-V1"
    assert sample["calibrated_value"] == 79.0
    assert workflow.find_row("alarm_result", confirmed["结果单号"]) is not None
