"""校准生效审批工作流接口。

通用资源接口仍可访问 calibration_verification / calibration_approval；
本路由提供跨“检定行—系数版本—在途采样—告警结果—待办”的聚合操作。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.services.calibration import workflow

router = APIRouter(prefix="/api/calibration", tags=["校准生效审批"])


def _ok_or_404(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok") and result.get("status_code") == 404:
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@router.get("/scenario")
def get_scenario() -> dict[str, Any]:
    return workflow.scenario()


@router.post("/scenario/reset")
def reset_scenario() -> dict[str, Any]:
    return workflow.reset_scenario()


@router.post("/rule")
def configure_rule(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return workflow.configure_alarm_rule(
        str(payload.get("operator", ">")),
        payload.get("threshold", payload.get("阈值", 80)),
    )


@router.post("/original-reading/confirm")
def confirm_original_reading() -> dict[str, Any]:
    return workflow.confirm_original_79()


@router.post("/verification/process")
@router.post("/verification/batch")
@router.post("/verification/import")
def process_verification_rows(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return workflow.process_verification_payload(payload)


@router.post("/verification/{row_ref}/validate")
def validate_verification_row(row_ref: str) -> dict[str, Any]:
    result = workflow.validate_verification(row_ref)
    if not result.get("ok"):
        # 行级业务退回仍返回 200，便于审批页面逐行留证；调用方读取 ok/rejected。
        return result
    return result


@router.post("/verification/{row_ref}/submit")
def submit_verification_row(row_ref: str) -> dict[str, Any]:
    return workflow.create_approval(row_ref)


@router.get("/approvals")
def list_approvals() -> dict[str, Any]:
    return {"ok": True, "items": workflow.scenario()["approvals"]}


@router.get("/approvals/{approval_ref}")
def get_approval(approval_ref: str) -> dict[str, Any]:
    return _ok_or_404(workflow.approval_detail(approval_ref))


@router.post("/approvals/{approval_ref}/approve")
def approve_approval(approval_ref: str) -> dict[str, Any]:
    return _ok_or_404(workflow.approve_approval(approval_ref))


@router.post("/approvals/{approval_ref}/activate")
@router.post("/approvals/{approval_ref}/effective")
@router.post("/approvals/{approval_ref}/publish")
def activate_approval(approval_ref: str) -> dict[str, Any]:
    return _ok_or_404(workflow.activate_approval(approval_ref))


@router.post("/approvals/{approval_ref}/approve-and-activate")
def approve_and_activate(approval_ref: str) -> dict[str, Any]:
    approved = workflow.approve_approval(approval_ref)
    if not approved.get("ok") and "已是" not in approved.get("message", ""):
        return _ok_or_404(approved)
    return _ok_or_404(workflow.activate_approval(approval_ref))


@router.post("/approvals/{approval_ref}/resolve-conflict")
@router.post("/approvals/{approval_ref}/recompute")
def resolve_conflict(
    approval_ref: str,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    sample_ref = payload.get("sample_id") or payload.get("采样单号")
    return _ok_or_404(workflow.resolve_conflict(approval_ref, sample_ref))


@router.post("/samples")
def record_sample(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return workflow.record_sample(payload)


@router.post("/samples/{sample_ref}/evaluate")
def evaluate_sample(sample_ref: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    version_ref = payload.get("coefficient_version") or payload.get("系数版本")
    return workflow.evaluate_sample(sample_ref, version_ref)


@router.post("/samples/{sample_ref}/confirm")
def confirm_sample(sample_ref: str) -> dict[str, Any]:
    return workflow.confirm_sample(sample_ref)


@router.post("/evaluate")
def evaluate_value(
    payload: dict[str, Any] = Body(default_factory=dict),
    point_id: str | None = None,
    current_value: float | None = None,
    device_id: str | None = None,
    probe_identity: str | None = None,
    sampled_at: str | None = None,
) -> dict[str, Any]:
    """无状态语义入口：先记录采样并立即按有效系数版本判定。

    同时兼容 JSON body 和与 /api/cross/flow5/evaluate 一致的 query 参数。
    """
    values = dict(payload)
    query_values = {
        "point_id": point_id,
        "current_value": current_value,
        "device_id": device_id,
        "probe_identity": probe_identity,
        "sampled_at": sampled_at,
    }
    values.update({key: value for key, value in query_values.items() if value is not None})
    created = workflow.record_sample(values)
    if not created.get("ok"):
        return created
    return created.get("evaluation", {"ok": False, "message": "未完成评估"})
