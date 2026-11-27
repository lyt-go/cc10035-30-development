"""探头检定 → 校准系数版本 → 生效审批 → 告警判定的一体化领域服务。

这里刻意不按“探头名称”关联系数：现场存在同名探头，身份键必须是
``(设备编号, 探头实际身份)``。所有采样判定都会固化所采用版本的乘数和偏移，
避免审批在在途采样期间生效时混用两个版本的系数。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

CST = timezone(timedelta(hours=8))

VERIFICATION = "calibration_verification"
APPROVAL = "calibration_approval"
COEFFICIENT = "calibration_coefficient"
SAMPLE = "sample_reading"
RESULT = "alarm_result"
TODO = "approval_todo"

DEFAULT_MULTIPLIER_RANGE = (0.5, 2.0)
DEFAULT_OFFSET_RANGE = (-100.0, 100.0)

UNIT_ALIASES = {
    "℃": "℃",
    "°c": "℃",
    "c": "℃",
    "degc": "℃",
    "degreecelsius": "℃",
    "v": "V",
    "volt": "V",
    "voltage": "V",
    "mpa": "MPa",
    "kpa": "kPa",
    "pa": "Pa",
    "a": "A",
    "ma": "mA",
}

UNIT_DIMENSION = {
    "℃": "temperature",
    "V": "voltage",
    "MPa": "pressure",
    "kPa": "pressure",
    "Pa": "pressure",
    "A": "current",
    "mA": "current",
}


def now_dt() -> datetime:
    return datetime.now(CST)


def now_iso() -> str:
    return now_dt().isoformat(timespec="seconds")


def pick(values: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in values and values[key] is not None and str(values[key]) != "":
            return values[key]
    return default


def identity_key(device_id: str, probe_identity: str) -> str:
    return f"{device_id}::{probe_identity}"


def parse_datetime(value: Any, *, default_now: bool = True) -> datetime | None:
    if value is None or value == "":
        return now_dt() if default_now else None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        # 兼容 “2026-11-27 08:00:00” 这种空格分隔形式。
        if " " in text and "T" not in text:
            text = text.replace(" ", "T")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt


def iso_or_none(value: Any) -> str:
    dt = parse_datetime(value, default_now=False)
    return dt.isoformat(timespec="seconds") if dt else ""


def parse_number(value: Any) -> tuple[float | None, str]:
    if isinstance(value, bool):
        return None, "不能把布尔值作为数值"
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str("" if value is None else value).strip()
        if text == "":
            return None, "数值为空"
        # 允许中文输入里常见的全角加号。
        text = text.replace("＋", "+").replace("，", ".")
        try:
            number = float(text)
        except ValueError:
            return None, f"数值「{value}」不是合法数字"
    if not math.isfinite(number):
        return None, "数值不能是 NaN 或无穷大"
    return number, ""


def normalize_unit(value: Any) -> tuple[str | None, str]:
    text = str(value or "").strip()
    if not text:
        return None, "单位为空"
    compact = text.replace(" ", "").replace("　", "")
    canonical = UNIT_ALIASES.get(compact.casefold())
    if canonical is None:
        return None, f"非法单位「{text}」"
    return canonical, ""


def canonical_unit(value: Any) -> tuple[str, bool]:
    """返回标准符号及是否在单位字典中；未收录单位保留原文，便于按行判错。"""
    text = str(value or "").strip()
    compact = text.replace(" ", "").replace("　", "")
    if not compact:
        return "", False
    canonical = UNIT_ALIASES.get(compact.casefold())
    return (canonical, True) if canonical else (compact, False)


def parse_range(value: Any) -> tuple[float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    for sep in ("~", "～", ",", "，"):
        if sep in text:
            parts = text.split(sep, 1)
            try:
                return float(parts[0].strip("[]() ")), float(parts[1].strip("[]() "))
            except ValueError:
                return None
    return None


def next_business_id(rows: list[dict[str, Any]], field: str, prefix: str) -> str:
    max_no = 0
    for row in rows:
        text = str(row.get(field, ""))
        if text.startswith(prefix):
            tail = text[len(prefix):]
            try:
                max_no = max(max_no, int(tail))
            except ValueError:
                pass
    return f"{prefix}{max_no + 1:04d}"


class CalibrationWorkflow:
    """所有校准状态流转的唯一入口；路由层只做参数转发。"""

    def __init__(self) -> None:
        self.ensure_seed()

    # ---------- 种子与重置 ----------

    def ensure_seed(self) -> None:
        self._upsert_core_definitions()
        if not store.rows(VERIFICATION):
            self._seed_scenario()

    def reset_scenario(self) -> dict[str, Any]:
        for table in (VERIFICATION, APPROVAL, COEFFICIENT, SAMPLE, RESULT, TODO):
            store._tables.pop(table, None)
        self._upsert_core_definitions()
        self._seed_scenario()
        return self.scenario()

    def _upsert_core_definitions(self) -> None:
        points = store.rows("ts_point")
        point_specs = [
            {
                "id": 9101,
                "测点编号": "TS_P-CAL-80",
                "设备编号": "DEVI-0001",
                "探头实际身份": "PRB-A-0001",
                "测点名称": "温度探头",
                "数据类型": "float64",
                "采集间隔": "10s",
                "上报方式": "mqtt",
                "单位符号": "℃",
                "量程范围": "0-150",
                "status": "采集中",
                "pending": False,
                "abnormal": False,
            },
            {
                "id": 9102,
                "测点编号": "TS_P-CAL-80-B",
                "设备编号": "DEVI-0002",
                "探头实际身份": "PRB-B-0002",
                "测点名称": "温度探头",
                "数据类型": "float64",
                "采集间隔": "10s",
                "上报方式": "mqtt",
                "单位符号": "℃",
                "量程范围": "0-150",
                "status": "采集中",
                "pending": False,
                "abnormal": False,
            },
        ]
        for spec in point_specs:
            existing = next((row for row in points if row.get("测点编号") == spec["测点编号"]), None)
            if existing is None:
                points.append(dict(spec))
            else:
                existing.update(spec)

        alarms = store.rows("alarm_trigger")
        rule = {
            "id": 9101,
            "规则编号": "ALARM-CAL-80",
            "关联测点": "TS_P-CAL-80",
            "告警条件": "严格大于（>）",
            "operator": ">",
            "阈值上限": "80",
            "阈值": 80,
            "阈值下限": "",
            "持续秒数": "0",
            "告警级别": "严重",
            "通知方式": "生效审批详情留证 + 待办回查",
            "status": "已启用",
            "pending": False,
            "abnormal": False,
        }
        existing_rule = next((row for row in alarms if row.get("规则编号") == rule["规则编号"]), None)
        if existing_rule is None:
            alarms.append(rule)
        else:
            existing_rule.update(rule)

    def _seed_scenario(self) -> None:
        start = (now_dt() - timedelta(days=1)).replace(microsecond=0).isoformat()
        end = (now_dt() + timedelta(days=365)).replace(microsecond=0).isoformat()
        sampled_at = now_dt().replace(microsecond=0).isoformat()

        store.rows(COEFFICIENT).extend([
            {
                "id": 9101,
                "系数版本": "CAL-COEF-V1",
                "version_number": 1,
                "identity_key": identity_key("DEVI-0001", "PRB-A-0001"),
                "设备编号": "DEVI-0001",
                "探头实际身份": "PRB-A-0001",
                "探头名称": "温度探头",
                "单位": "℃",
                "multiplier": 1.0,
                "offset": 0.0,
                "valid_start": start,
                "valid_end": end,
                "时段开始": start,
                "时段结束": end,
                "status": "已生效",
                "source": "基线系数",
            },
            {
                "id": 9102,
                "系数版本": "CAL-COEF-OTHER-V1",
                "version_number": 1,
                "identity_key": identity_key("DEVI-0002", "PRB-B-0002"),
                "设备编号": "DEVI-0002",
                "探头实际身份": "PRB-B-0002",
                "探头名称": "温度探头",
                "单位": "℃",
                "multiplier": 1.0,
                "offset": 0.0,
                "valid_start": start,
                "valid_end": end,
                "时段开始": start,
                "时段结束": end,
                "status": "已生效",
                "source": "同名探头独立基线",
            },
        ])

        store.rows(VERIFICATION).extend([
            {
                "id": 9101,
                "检定行号": "CAL-VER-OFFSET2",
                "批次号": "CAL-BATCH-001",
                "设备编号": "DEVI-0001",
                "探头名称": "温度探头",
                "探头实际身份": "PRB-A-0001",
                "测点编号": "TS_P-CAL-80",
                "标准单位": "℃",
                "检定单位": "℃",
                "原始示值": "79",
                "标准示值": "81",
                "乘数": "1.000",
                "偏移": "+2",
                "乘数允许区间": "0.80~1.20",
                "偏移允许区间": "-5.00~5.00",
                "时段开始": start,
                "时段结束": end,
                "status": "待办理",
                "pending": True,
                "abnormal": False,
                "校验结果": "",
                "处理意见": "合格偏移 +2，等待按行提交生效审批",
            },
            {
                "id": 9102,
                "检定行号": "CAL-VER-BAD-UNIT",
                "批次号": "CAL-BATCH-001",
                "设备编号": "DEVI-0001",
                "探头名称": "温度探头",
                "探头实际身份": "PRB-A-0001",
                "测点编号": "TS_P-CAL-80",
                "标准单位": "℃",
                "检定单位": "V",
                "原始示值": "79",
                "标准示值": "81",
                "乘数": "1.000",
                "偏移": "2",
                "乘数允许区间": "0.80~1.20",
                "偏移允许区间": "-5.00~5.00",
                "时段开始": start,
                "时段结束": end,
                "status": "待办理",
                "pending": True,
                "abnormal": False,
                "校验结果": "",
                "处理意见": "故意错单位行，应按行退回且不影响合法行",
            },
        ])

        store.rows(SAMPLE).extend([
            {
                "id": 9101,
                "采样单号": "SR-HIST-79",
                "采样用途": "先确认原值不触发",
                "identity_key": identity_key("DEVI-0001", "PRB-A-0001"),
                "设备编号": "DEVI-0001",
                "探头实际身份": "PRB-A-0001",
                "探头名称": "温度探头",
                "测点编号": "TS_P-CAL-80",
                "raw_value": 79.0,
                "单位": "℃",
                "sampled_at": sampled_at,
                "status": "待确认",
                "在途": False,
                "confirmation_status": "待确认",
                "coefficient_version": "CAL-COEF-V1",
                "multiplier": 1.0,
                "offset": 0.0,
                "calibrated_value": 79.0,
                "operator": ">",
                "threshold": 80.0,
                "triggered": False,
                "version_status": "版本一致",
                "version_conflict": False,
                "history": [],
            },
            {
                "id": 9102,
                "采样单号": "SR-INFLIGHT-79",
                "采样用途": "审批生效到达时仍未确认的在途读数",
                "identity_key": identity_key("DEVI-0001", "PRB-A-0001"),
                "设备编号": "DEVI-0001",
                "探头实际身份": "PRB-A-0001",
                "探头名称": "温度探头",
                "测点编号": "TS_P-CAL-80",
                "raw_value": 79.0,
                "单位": "℃",
                "sampled_at": sampled_at,
                "status": "待确认",
                "在途": True,
                "confirmation_status": "在途/待确认",
                "coefficient_version": "CAL-COEF-V1",
                "multiplier": 1.0,
                "offset": 0.0,
                "calibrated_value": 79.0,
                "operator": ">",
                "threshold": 80.0,
                "triggered": False,
                "version_status": "版本一致",
                "version_conflict": False,
                "history": [],
            },
        ])

    # ---------- 查询与标识 ----------

    def scenario(self) -> dict[str, Any]:
        return {
            "ok": True,
            "rule": self.alarm_rule(),
            "identity_note": "同名探头按 设备编号 + 探头实际身份 隔离",
            "verifications": store.rows(VERIFICATION),
            "approvals": store.rows(APPROVAL),
            "coefficients": store.rows(COEFFICIENT),
            "samples": store.rows(SAMPLE),
            "alarm_results": store.rows(RESULT),
            "todos": store.rows(TODO),
        }

    def alarm_rule(self) -> dict[str, Any]:
        rule = next(
            (row for row in store.rows("alarm_trigger") if row.get("规则编号") == "ALARM-CAL-80"),
            {},
        )
        return rule

    def configure_alarm_rule(self, operator: str = ">", threshold: Any = 80) -> dict[str, Any]:
        value, error = parse_number(threshold)
        if error or value is None:
            return {"ok": False, "message": f"阈值不合法：{error}"}
        if operator not in (">", "<", ">=", "<="):
            return {"ok": False, "message": f"不支持的比较符：{operator}"}
        self._upsert_core_definitions()
        rule = self.alarm_rule()
        rule["operator"] = operator
        rule["阈值"] = value
        if operator in (">", ">="):
            rule["阈值上限"] = str(value)
        else:
            rule["阈值下限"] = str(value)
        strict_text = "严格大于" if operator == ">" else "严格小于" if operator == "<" else operator
        rule["告警条件"] = f"{strict_text}（{operator}）"
        rule["status"] = "已启用"
        rule["pending"] = False
        return {"ok": True, "message": f"告警规则已设置为 {operator} {value:g}", "rule": rule}

    def find_row(self, table: str, ref: str | int) -> dict[str, Any] | None:
        text = str(ref)
        rows = store.rows(table)
        id_fields = {
            VERIFICATION: "检定行号",
            APPROVAL: "审批单号",
            SAMPLE: "采样单号",
            TODO: "待办单号",
            RESULT: "结果单号",
            COEFFICIENT: "系数版本",
        }.get(table, "编号")
        row = next((item for item in rows if str(item.get(id_fields, "")) == text), None)
        if row is not None:
            return row
        try:
            numeric_id = int(ref)
        except (TypeError, ValueError):
            return None
        return store.find(table, numeric_id)

    def approval_detail(self, ref: str | int) -> dict[str, Any]:
        approval = self.find_row(APPROVAL, ref)
        if approval is None:
            return {"ok": False, "status_code": 404, "message": f"生效审批单 {ref} 不存在"}
        apr_id = approval["审批单号"]
        verification = self.find_row(VERIFICATION, approval.get("检定行号", ""))
        coefficient = next(
            (row for row in store.rows(COEFFICIENT) if row.get("系数版本") == approval.get("系数版本")),
            None,
        )
        todos = [row for row in store.rows(TODO) if row.get("审批单号") == apr_id]
        results = [row for row in store.rows(RESULT) if row.get("审批单号") == apr_id]
        sample_ids = set(approval.get("conflict_sample_ids", []))
        conflict_samples = [
            row for row in store.rows(SAMPLE)
            if row.get("采样单号") in sample_ids or (
                row.get("审批单号") == apr_id and row.get("version_conflict")
            )
        ]
        return {
            "ok": True,
            "approval": approval,
            "verification_row": verification,
            "coefficient": coefficient,
            "todos": todos,
            "alarm_results": results,
            "conflict_samples": conflict_samples,
            "evidence": approval.get("evidence", []),
            "trace": {
                "approval_id": apr_id,
                "verification_row": approval.get("检定行号"),
                "todo_ids": [row.get("待办单号") for row in todos],
                "alarm_result_ids": [row.get("结果单号") for row in results],
            },
        }

    # ---------- 检定行校验 ----------

    def validate_verification(self, row_ref: str | int) -> dict[str, Any]:
        row = self.find_row(VERIFICATION, row_ref)
        if row is None:
            return {"ok": False, "message": f"检定行 {row_ref} 不存在"}

        errors: list[str] = []
        device_id = str(pick(row, "设备编号", "device_id")).strip()
        probe_identity = str(pick(
            row,
            "探头实际身份", "实际身份", "探头身份", "实际身份编号",
            "probe_identity", "probe_serial", "probe_code", "serial_no", "identity",
        )).strip()
        if not device_id:
            errors.append("缺少设备编号")
        if not probe_identity:
            errors.append("缺少探头实际身份")

        standard_unit, standard_known = canonical_unit(
            pick(row, "标准单位", "standard_unit", default=row.get("检定单位", ""))
        )
        calibration_unit, calibration_known = canonical_unit(pick(row, "检定单位", "unit", "单位"))
        if not standard_unit:
            errors.append("标准单位为空")
        if not calibration_unit:
            errors.append("检定单位为空")
        elif standard_unit and calibration_unit and standard_unit != calibration_unit:
            errors.append(
                f"单位不一致或非法：检定单位「{row.get('检定单位')}」必须等同标准单位「{row.get('标准单位')}」"
            )
        elif standard_known and not calibration_known:
            errors.append(f"非法单位「{row.get('检定单位')}」")

        multiplier, number_error = parse_number(pick(row, "乘数", "multiplier"))
        if number_error:
            errors.append(f"乘数{number_error}")
        elif multiplier is not None:
            low, high = parse_range(row.get("乘数允许区间")) or DEFAULT_MULTIPLIER_RANGE
            if not (low <= multiplier <= high) or multiplier == 0:
                errors.append(f"乘数 {multiplier} 不在有效区间 [{low}, {high}] 内")

        offset, offset_error = parse_number(pick(row, "偏移", "offset"))
        if offset_error:
            errors.append(f"偏移{offset_error}")
        elif offset is not None:
            low, high = parse_range(row.get("偏移允许区间")) or DEFAULT_OFFSET_RANGE
            if not (low <= offset <= high):
                errors.append(f"偏移 {offset} 不在有效区间 [{low}, {high}] 内")

        valid_start = parse_datetime(pick(row, "时段开始", "valid_start", "effective_start"), default_now=False)
        valid_end = parse_datetime(pick(row, "时段结束", "valid_end", "effective_end"), default_now=False)
        if row.get("时段开始") and valid_start is None:
            errors.append("时段开始不是合法时间")
        if row.get("时段结束") and valid_end is None:
            errors.append("时段结束不是合法时间")
        if valid_start and valid_end and valid_end < valid_start:
            errors.append("时段结束早于时段开始")

        row["校验时间"] = now_iso()
        if errors:
            row["status"] = "已退回"
            row["pending"] = False
            row["abnormal"] = True
            row["校验结果"] = "不通过"
            row["处理意见"] = "；".join(errors)
            row["退回原因"] = row["处理意见"]
            return {"ok": False, "rejected": True, "message": row["处理意见"], "row": row}

        row["status"] = "校验通过"
        row["pending"] = True
        row["abnormal"] = False
        row["校验结果"] = "合格"
        row["处理意见"] = "数值、单位和有效时段均合格，可建立生效审批单"
        row["normalized_unit"] = calibration_unit
        row["multiplier_value"] = multiplier
        row["offset_value"] = offset
        return {"ok": True, "accepted": True, "message": "检定行校验合格", "row": row}

    def process_verification_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = payload.get("rows")
        batch_id = payload.get("batch_id") or payload.get("批次号")
        if isinstance(rows, list):
            created = []
            for values in rows:
                created.append(self.create_verification(values))
            targets = [item["row"]["检定行号"] for item in created if item.get("row")]
        elif batch_id:
            targets = [
                row["检定行号"] for row in store.rows(VERIFICATION)
                if row.get("批次号") == str(batch_id)
            ]
            if not targets:
                return {"ok": False, "message": f"批次 {batch_id} 没有检定行"}
        else:
            targets = [row["检定行号"] for row in store.rows(VERIFICATION)]

        results = [self.validate_verification(ref) for ref in targets]
        accepted = [item for item in results if item.get("ok")]
        rejected = [item for item in results if not item.get("ok")]

        approval_results = []
        if bool(payload.get("auto_submit", False)):
            for item in accepted:
                approval_results.append(self.create_approval(item["row"]["检定行号"]))

        return {
            "ok": True,
            "message": f"按行办理完成：合格 {len(accepted)} 行，退回 {len(rejected)} 行；退回行未替换当前系数",
            "total": len(results),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "accepted": accepted,
            "rejected": rejected,
            "approval_results": approval_results,
            "current_coefficients": store.rows(COEFFICIENT),
        }

    def create_verification(self, values: dict[str, Any]) -> dict[str, Any]:
        rows = store.rows(VERIFICATION)
        ref = str(pick(values, "检定行号", "verification_id", default="")).strip()
        if not ref:
            ref = next_business_id(rows, "检定行号", "CAL-VER-")
        row = {
            "id": max((int(item.get("id", 0)) for item in rows), default=9000) + 1,
            "检定行号": ref,
            "批次号": str(pick(values, "批次号", "batch_id", default="CAL-BATCH-NEW")),
            "设备编号": str(pick(values, "设备编号", "device_id")),
            "探头名称": str(pick(values, "探头名称", "probe_name", "name")),
            "探头实际身份": str(pick(
                values,
                "探头实际身份", "实际身份", "探头身份", "实际身份编号",
                "probe_identity", "probe_serial", "probe_code", "serial_no", "identity",
            )),
            "测点编号": str(pick(values, "测点编号", "point_id")),
            "标准单位": str(pick(values, "标准单位", "standard_unit", default="℃")),
            "检定单位": str(pick(values, "检定单位", "unit", "单位")),
            "原始示值": str(pick(values, "原始示值", "raw_value", default="")),
            "标准示值": str(pick(values, "标准示值", "standard_value", default="")),
            "乘数": str(pick(values, "乘数", "multiplier", default="1")),
            "偏移": str(pick(values, "偏移", "offset", default="0")),
            "乘数允许区间": str(pick(values, "乘数允许区间", default="")),
            "偏移允许区间": str(pick(values, "偏移允许区间", default="")),
            "时段开始": iso_or_none(pick(values, "时段开始", "valid_start")) or pick(values, "时段开始", "valid_start"),
            "时段结束": iso_or_none(pick(values, "时段结束", "valid_end")) or pick(values, "时段结束", "valid_end"),
            "status": "待办理",
            "pending": True,
            "abnormal": False,
            "校验结果": "",
            "处理意见": "",
        }
        rows.append(row)
        return {"ok": True, "row": row}

    # ---------- 审批 ----------

    def create_approval(self, row_ref: str | int) -> dict[str, Any]:
        checked = self.validate_verification(row_ref)
        if not checked.get("ok"):
            return {
                "ok": False,
                "message": f"检定行未通过校验，不能建立审批单：{checked.get('message')}",
                "validation": checked,
            }
        row = checked["row"]
        existing = next(
            (apr for apr in store.rows(APPROVAL) if apr.get("检定行号") == row["检定行号"]),
            None,
        )
        if existing is not None:
            return {"ok": True, "message": "审批单已存在", "approval": existing, "already_exists": True}

        device_id = row["设备编号"]
        probe_identity = row["探头实际身份"]
        key = identity_key(device_id, probe_identity)
        versions = [item for item in store.rows(COEFFICIENT) if item.get("identity_key") == key]
        version_number = max((int(item.get("version_number", 1)) for item in versions), default=0) + 1
        version_id = f"CAL-COEF-V{version_number}"
        # 种子已有 V1；若动态环境中业务编号冲突，追加短标识仍保持版本号可追溯。
        if any(item.get("系数版本") == version_id for item in store.rows(COEFFICIENT)):
            version_id = f"CAL-COEF-{row['检定行号']}"

        apr_no = next_business_id(store.rows(APPROVAL), "审批单号", "CAL-APR-")
        todo_no = next_business_id(store.rows(TODO), "待办单号", "TODO-APR-")
        start = row.get("时段开始") or now_iso()
        end = row.get("时段结束") or (now_dt() + timedelta(days=365)).isoformat(timespec="seconds")

        coefficient = {
            "id": max((int(item.get("id", 0)) for item in store.rows(COEFFICIENT)), default=9100) + 1,
            "系数版本": version_id,
            "version_number": version_number,
            "identity_key": key,
            "设备编号": device_id,
            "探头实际身份": probe_identity,
            "探头名称": row.get("探头名称", ""),
            "单位": row.get("normalized_unit") or row.get("检定单位"),
            "multiplier": float(row["multiplier_value"]),
            "offset": float(row["offset_value"]),
            "valid_start": start,
            "valid_end": end,
            "时段开始": start,
            "时段结束": end,
            "status": "待审批",
            "source": row["检定行号"],
        }
        store.rows(COEFFICIENT).append(coefficient)

        approval = {
            "id": max((int(item.get("id", 0)) for item in store.rows(APPROVAL)), default=9100) + 1,
            "审批单号": apr_no,
            "检定行号": row["检定行号"],
            "批次号": row.get("批次号", ""),
            "设备编号": device_id,
            "探头名称": row.get("探头名称", ""),
            "探头实际身份": probe_identity,
            "identity_key": key,
            "系数版本": version_id,
            "乘数": coefficient["multiplier"],
            "偏移": coefficient["offset"],
            "单位": coefficient["单位"],
            "时段开始": start,
            "时段结束": end,
            "alarm_rule": "ALARM-CAL-80",
            "alarm_action": "严格大于 80 时触发告警并在本单留证",
            "status": "待审批",
            "pending": True,
            "abnormal": False,
            "conflict_status": "尚未生效",
            "conflict_sample_ids": [],
            "todo_ids": [todo_no],
            "alarm_result_ids": [],
            "evidence": [
                {
                    "at": now_iso(),
                    "type": "检定行关联",
                    "message": f"检定行 {row['检定行号']} 校验合格，生成系数版本 {version_id} 和生效审批单 {apr_no}",
                    "检定行号": row["检定行号"],
                    "系数版本": version_id,
                }
            ],
        }
        store.rows(APPROVAL).append(approval)
        store.rows(TODO).append({
            "id": max((int(item.get("id", 0)) for item in store.rows(TODO)), default=9100) + 1,
            "待办单号": todo_no,
            "审批单号": apr_no,
            "类型": "审批生效",
            "标题": f"审批并发布 {apr_no} 的分时校准系数 {version_id}",
            "status": "待处理",
            "pending": True,
            "created_at": now_iso(),
            "completed_at": "",
            "链接": f"/calibration/approvals/{apr_no}",
        })
        row["审批单号"] = apr_no
        return {"ok": True, "message": "已建立从检定行到告警动作的生效审批单", "approval": approval}

    def run_approval_action(self, ref: str | int, action: str) -> dict[str, Any]:
        if action in ("审批通过", "approve"):
            return self.approve_approval(ref)
        if action in ("发布生效", "审批通过并生效", "生效", "activate"):
            approved = self.approve_approval(ref)
            if not approved.get("ok") and "已批准" not in approved.get("message", ""):
                return approved
            return self.activate_approval(ref)
        if action in ("处理冲突并重算", "使用同一版本重算", "resolve"):
            return self.resolve_conflict(ref)
        return {"ok": False, "message": f"不支持的审批动作：{action}"}

    def approve_approval(self, ref: str | int) -> dict[str, Any]:
        detail = self.approval_detail(ref)
        if not detail.get("ok"):
            return detail
        approval = detail["approval"]
        if approval["status"] in ("已批准", "已生效"):
            return {"ok": True, "message": f"审批单已是{approval['status']}", "approval": approval}
        approval["status"] = "已批准"
        approval["approved_at"] = now_iso()
        approval["evidence"].append({"at": now_iso(), "type": "审批通过", "message": "审批通过，等待生效到达"})
        return {"ok": True, "message": "审批已通过", "approval": approval}

    def activate_approval(self, ref: str | int) -> dict[str, Any]:
        detail = self.approval_detail(ref)
        if not detail.get("ok"):
            return detail
        approval = detail["approval"]
        if approval.get("status") == "已生效":
            return {
                "ok": True,
                "idempotent": True,
                "conflict": "待处理" in str(approval.get("conflict_status", "")),
                "message": "审批单已处于生效状态，重复生效请求未重复生成版本或待办",
                "detail": self.approval_detail(ref),
            }
        if approval.get("status") == "待审批":
            self.approve_approval(ref)
        coefficient = next(
            (row for row in store.rows(COEFFICIENT) if row.get("系数版本") == approval["系数版本"]),
            None,
        )
        if coefficient is None:
            return {"ok": False, "message": "审批单引用的系数版本不存在"}

        approval["status"] = "已生效"
        approval["pending"] = False
        approval["effective_at"] = now_iso()
        coefficient["status"] = "已生效"

        todo = next(
            (row for row in store.rows(TODO)
             if row.get("审批单号") == approval["审批单号"] and row.get("类型") == "审批生效"),
            None,
        )
        if todo is not None:
            todo["status"] = "已完成"
            todo["pending"] = False
            todo["completed_at"] = now_iso()

        conflicts = self._detect_conflicts(approval, coefficient)
        if conflicts:
            todo_no = next_business_id(store.rows(TODO), "待办单号", "TODO-CONFLICT-")
            sample_ids = [row["采样单号"] for row in conflicts]
            approval["conflict_status"] = "待处理确认：已按同一新版本预演告警"
            approval["conflict_sample_ids"] = sample_ids
            approval["todo_ids"].append(todo_no)
            todo = {
                "id": max((int(item.get("id", 0)) for item in store.rows(TODO)), default=9200) + 1,
                "待办单号": todo_no,
                "审批单号": approval["审批单号"],
                "类型": "版本冲突核对",
                "标题": f"确认在途采样 {', '.join(sample_ids)} 与 {coefficient['系数版本']} 的版本冲突处理",
                "status": "待处理",
                "pending": True,
                "created_at": now_iso(),
                "completed_at": "",
                "链接": f"/calibration/approvals/{approval['审批单号']}",
            }
            store.rows(TODO).append(todo)

            pre_results = []
            for conflict_sample in conflicts:
                evaluation = self.evaluate_sample(
                    conflict_sample["采样单号"],
                    coefficient["系数版本"],
                    approval_no=approval["审批单号"],
                )
                if evaluation.get("ok"):
                    result = evaluation["result"]
                    pre_results.append(result)
                    if result["结果单号"] not in approval["alarm_result_ids"]:
                        approval["alarm_result_ids"].append(result["结果单号"])
            if pre_results:
                todo["预演结果"] = "；".join(
                    f"{item['结果单号']}={item['raw_value']}×{item['multiplier']}+{item['offset']}"
                    f"={item['calibrated_value']}, triggered={item['triggered']}"
                    for item in pre_results
                )

            approval["evidence"].append({
                "at": now_iso(),
                "type": "版本冲突",
                "message": (
                    f"生效到达时发现 {len(conflicts)} 笔尚未确认且与本变更时段相交的采样；"
                    "不得跨版本拼凑乘数和偏移。告警服务已按同一新版本的两项系数预演，"
                    "告警数值、版本和待办均在本单留证，等待人工确认关闭待办"
                ),
                "sample_ids": sample_ids,
                "todo_id": todo_no,
                "alarm_result_ids": [item["结果单号"] for item in pre_results],
            })
            message = (
                f"审批已生效，发现在途读数版本冲突；已按同一 {coefficient['系数版本']} "
                "系数生成告警判定并留下待办"
            )
        else:
            approval["conflict_status"] = "无冲突"
            approval["evidence"].append({"at": now_iso(), "type": "生效", "message": "系数版本已在获准时段生效"})
            message = "审批已生效，未发现相交的在途采样"

        return {"ok": True, "conflict": bool(conflicts), "message": message, "detail": self.approval_detail(ref)}

    def _detect_conflicts(self, approval: dict[str, Any], coefficient: dict[str, Any]) -> list[dict[str, Any]]:
        start = parse_datetime(coefficient.get("valid_start"))
        end = parse_datetime(coefficient.get("valid_end"))
        found = []
        for sample in store.rows(SAMPLE):
            if sample.get("identity_key") != coefficient["identity_key"]:
                continue
            if sample.get("status") == "已确认":
                continue
            sampled_at = parse_datetime(sample.get("sampled_at"))
            if sampled_at is None or start is None or end is None:
                continue
            if not (start <= sampled_at <= end):
                continue
            if sample.get("coefficient_version") == coefficient["系数版本"]:
                continue
            sample["pre_conflict_snapshot"] = {
                "coefficient_version": sample.get("coefficient_version"),
                "multiplier": sample.get("multiplier"),
                "offset": sample.get("offset"),
                "calibrated_value": sample.get("calibrated_value"),
                "captured_at": now_iso(),
            }
            sample["version_conflict"] = True
            sample["version_status"] = "版本冲突：审批生效，采样尚未确认"
            sample["conflict_with"] = coefficient["系数版本"]
            sample["conflict_approval"] = approval["审批单号"]
            sample["审批单号"] = approval["审批单号"]
            found.append(sample)
        return found

    def resolve_conflict(self, ref: str | int, sample_ref: str | int | None = None) -> dict[str, Any]:
        detail = self.approval_detail(ref)
        if not detail.get("ok"):
            return detail
        approval = detail["approval"]
        if approval.get("status") != "已生效":
            return {"ok": False, "message": "审批单尚未生效，不能按生效版本处理冲突"}

        open_conflict_todo = any(
            row.get("审批单号") == approval["审批单号"] and row.get("类型") == "版本冲突核对"
            and row.get("status") != "已完成"
            for row in store.rows(TODO)
        )
        if not open_conflict_todo and str(approval.get("conflict_status", "")).startswith("已处理"):
            return {
                "ok": True,
                "idempotent": True,
                "message": "版本冲突已处理，告警结果和版本对应关系已在审批详情页留证",
                "detail": self.approval_detail(ref),
            }

        conflict_samples = detail["conflict_samples"]
        if sample_ref:
            sample = self.find_row(SAMPLE, sample_ref)
        elif conflict_samples:
            sample = conflict_samples[0]
        else:
            sample = next(
                (row for row in store.rows(SAMPLE)
                 if row.get("identity_key") == approval.get("identity_key")
                 and row.get("status") != "已确认"),
                None,
            )
        if sample is None:
            return {"ok": False, "message": "没有需要处理的在途采样"}

        result = next(
            (
                row for row in store.rows(RESULT)
                if row.get("采样单号") == sample["采样单号"]
                and row.get("审批单号") == approval["审批单号"]
                and row.get("coefficient_version") == approval.get("系数版本")
            ),
            None,
        )
        if result is None:
            evaluation = self.evaluate_sample(
                sample["采样单号"], approval.get("系数版本"), approval_no=approval["审批单号"]
            )
            if not evaluation.get("ok"):
                return evaluation
            result = evaluation["result"]

        sample["version_conflict"] = False
        sample["version_status"] = f"已按同一版本 {approval['系数版本']} 的乘数和偏移核对"
        sample["conflict_resolved_at"] = now_iso()

        if result.get("triggered"):
            approval["conflict_status"] = "已处理：新版本判定触发告警"
        else:
            approval["conflict_status"] = "已处理：新版本判定未触发"
        if result["结果单号"] not in approval["alarm_result_ids"]:
            approval["alarm_result_ids"].append(result["结果单号"])

        conflict_todo = next(
            (row for row in store.rows(TODO)
             if row.get("审批单号") == approval["审批单号"] and row.get("类型") == "版本冲突核对"
             and row.get("status") != "已完成"),
            None,
        )
        if conflict_todo is not None:
            conflict_todo["status"] = "已完成"
            conflict_todo["pending"] = False
            conflict_todo["completed_at"] = now_iso()
            conflict_todo["处理结果"] = f"{result['结果单号']}：校准值 {result['calibrated_value']}，触发={result['triggered']}"

        approval["evidence"].append({
            "at": now_iso(),
            "type": "冲突处理/告警动作",
            "message": (
                f"采样 {sample['采样单号']} 使用同一版本 {result['coefficient_version']} 的两项系数："
                f"{result['raw_value']}×{result['multiplier']}+{result['offset']}"
                f"={result['calibrated_value']}；{result['operator']} {result['threshold']} "
                f"判定触发={result['triggered']}，结果 {result['结果单号']}"
            ),
            "sample_id": sample["采样单号"],
            "alarm_result_id": result["结果单号"],
            "coefficient_version": result["coefficient_version"],
            "raw_value": result["raw_value"],
            "multiplier": result["multiplier"],
            "offset": result["offset"],
            "calibrated_value": result["calibrated_value"],
            "triggered": result["triggered"],
        })
        return {"ok": True, "message": "版本冲突已用同一有效版本的两项系数处理，并生成可回查的告警结果", "detail": self.approval_detail(ref)}

    # ---------- 采样与告警 ----------

    def coefficient_for(self, key: str, sampled_at: datetime, version_ref: str | None = None) -> dict[str, Any] | None:
        rows = store.rows(COEFFICIENT)
        if version_ref:
            explicit = self.find_row(COEFFICIENT, version_ref)
            if explicit is None or explicit.get("identity_key") != key:
                return None
            start = parse_datetime(explicit.get("valid_start"))
            end = parse_datetime(explicit.get("valid_end"))
            if start and end and not (start <= sampled_at <= end):
                return None
            return explicit

        candidates = []
        for row in rows:
            if row.get("identity_key") != key:
                continue
            start = parse_datetime(row.get("valid_start"))
            end = parse_datetime(row.get("valid_end"))
            if start is None or end is None or not (start <= sampled_at <= end):
                continue
            if row.get("status") not in ("已生效",):
                continue
            candidates.append(row)
        if not candidates:
            return None
        return max(candidates, key=lambda row: int(row.get("version_number", 1)))

    def record_sample(self, values: dict[str, Any]) -> dict[str, Any]:
        device_id = str(pick(values, "设备编号", "device_id")).strip()
        probe_identity = str(pick(
            values,
            "探头实际身份", "实际身份", "探头身份", "实际身份编号",
            "probe_identity", "probe_serial", "probe_code", "serial_no", "identity",
        )).strip()
        probe_name = str(pick(values, "探头名称", "probe_name", "name")).strip()
        point_id = str(pick(values, "测点编号", "point_id")).strip()

        if point_id and not (device_id and probe_identity):
            point = next((row for row in store.rows("ts_point") if row.get("测点编号") == point_id), None)
            if point:
                device_id = device_id or str(point.get("设备编号", ""))
                probe_identity = probe_identity or str(point.get("探头实际身份", ""))
                probe_name = probe_name or str(point.get("测点名称", ""))

        if not device_id or not probe_identity:
            return {"ok": False, "message": "同名探头必须提供设备编号和探头实际身份"}

        raw, error = parse_number(pick(values, "raw_value", "current_value", "value", "原始值", "数值"))
        if error:
            return {"ok": False, "message": error}
        assert raw is not None

        unit, unit_error = normalize_unit(pick(values, "单位", "unit", default="℃"))
        if unit_error:
            return {"ok": False, "message": unit_error}

        sampled_at_value = pick(values, "sampled_at", "timestamp", "采样时间")
        sampled_at = parse_datetime(sampled_at_value)
        if sampled_at is None:
            return {"ok": False, "message": "采样时间不是合法时间"}
        assert sampled_at is not None

        key = identity_key(device_id, probe_identity)
        version_ref = pick(values, "coefficient_version", "系数版本", default="") or None
        coefficient = self.coefficient_for(key, sampled_at, version_ref)
        if coefficient is None:
            return {"ok": False, "message": "记录采样时找不到覆盖该时间且已生效的系数版本；乘数和偏移必须处于有效区间内"}

        calibrated = round(raw * float(coefficient["multiplier"]) + float(coefficient["offset"]), 6)
        rows = store.rows(SAMPLE)
        sample_no = str(pick(values, "采样单号", "sample_id", default="")).strip() or next_business_id(rows, "采样单号", "SR-")
        sample = {
            "id": max((int(row.get("id", 0)) for row in rows), default=9200) + 1,
            "采样单号": sample_no,
            "采样用途": str(pick(values, "采样用途", default="API记录采样")),
            "identity_key": key,
            "设备编号": device_id,
            "探头实际身份": probe_identity,
            "探头名称": probe_name,
            "测点编号": point_id,
            "raw_value": raw,
            "单位": unit,
            "sampled_at": sampled_at.isoformat(timespec="seconds"),
            "status": "待确认",
            "在途": bool(pick(values, "在途", default=True)),
            "confirmation_status": "在途/待确认",
            "coefficient_version": coefficient["系数版本"],
            "multiplier": float(coefficient["multiplier"]),
            "offset": float(coefficient["offset"]),
            "calibrated_value": calibrated,
            "version_status": "版本一致",
            "version_conflict": False,
            "history": [],
        }
        rows.append(sample)
        evaluate = bool(values.get("evaluate", True)) if isinstance(values, dict) else True
        evaluation = self.evaluate_sample(sample_no) if evaluate else {"ok": True}
        return {"ok": True, "sample": sample, "evaluation": evaluation}

    def evaluate_sample(
        self,
        sample_ref: str | int,
        version_ref: str | int | None = None,
        approval_no: str = "",
    ) -> dict[str, Any]:
        sample = self.find_row(SAMPLE, sample_ref)
        if sample is None:
            return {"ok": False, "message": f"采样 {sample_ref} 不存在"}

        sampled_at = parse_datetime(sample.get("sampled_at")) or now_dt()
        requested_version = version_ref or sample.get("coefficient_version")
        coefficient = self.coefficient_for(sample["identity_key"], sampled_at, str(requested_version) if requested_version else None)
        if coefficient is None and version_ref:
            return {"ok": False, "message": "指定系数版本不覆盖采样时间，不能用于该记录"}
        if coefficient is None:
            coefficient = self.coefficient_for(sample["identity_key"], sampled_at)
        if coefficient is None:
            return {"ok": False, "message": "采样时间不在任何有效系数区间内"}

        # 关键不变量：multiplier 和 offset 取自同一个 coefficient 记录/版本。
        used_version = str(coefficient["系数版本"])
        used_multiplier = float(coefficient["multiplier"])
        used_offset = float(coefficient["offset"])
        raw_value = float(sample["raw_value"])
        calibrated = round(raw_value * used_multiplier + used_offset, 6)

        rule = self._rule_for_sample(sample)
        operator = str(pick(rule, "operator", default=">"))
        try:
            threshold = float(rule.get("阈值", rule.get("阈值上限", 80)))
        except (TypeError, ValueError):
            threshold = 80.0
        triggered = calibrated > threshold if operator == ">" else calibrated < threshold if operator == "<" else calibrated >= threshold

        result_no = next_business_id(store.rows(RESULT), "结果单号", "ALM-RES-")
        result = {
            "id": max((int(row.get("id", 0)) for row in store.rows(RESULT)), default=9300) + 1,
            "结果单号": result_no,
            "alarm_event_id": f"ALM-EVT-{result_no[-4:]}",
            "采样单号": sample["采样单号"],
            "审批单号": approval_no or sample.get("审批单号", ""),
            "规则编号": rule.get("规则编号", "ALARM-CAL-80"),
            "identity_key": sample["identity_key"],
            "设备编号": sample.get("设备编号", ""),
            "探头实际身份": sample.get("探头实际身份", ""),
            "测点编号": sample.get("测点编号", ""),
            "raw_value": raw_value,
            "multiplier": used_multiplier,
            "offset": used_offset,
            "calibrated_value": calibrated,
            "operator": operator,
            "threshold": threshold,
            "triggered": bool(triggered),
            "coefficient_version": used_version,
            "coefficient_fields": {
                "multiplier_from_same_version": used_version,
                "offset_from_same_version": used_version,
            },
            "evaluated_at": now_iso(),
            "status": "已触发告警" if triggered else "未触发",
            "action": "生成告警并通知/在审批页留证" if triggered else "记录不触发判定",
            "message": (
                f"{raw_value:g}×{used_multiplier:g}+{used_offset:g}={calibrated:g}，"
                f"{operator} {threshold:g} 严格判定：{'触发' if triggered else '不触发'}"
            ),
        }
        store.rows(RESULT).append(result)

        sample["history"].append({
            "at": now_iso(),
            "result_id": result_no,
            "coefficient_version": used_version,
            "multiplier": used_multiplier,
            "offset": used_offset,
            "calibrated_value": calibrated,
            "triggered": triggered,
        })
        sample.update({
            "coefficient_version": used_version,
            "multiplier": used_multiplier,
            "offset": used_offset,
            "calibrated_value": calibrated,
            "operator": operator,
            "threshold": threshold,
            "triggered": bool(triggered),
            "last_result_id": result_no,
        })
        if approval_no:
            sample["审批单号"] = approval_no
        return {"ok": True, "triggered": bool(triggered), "result": result}

    def _rule_for_sample(self, sample: dict[str, Any]) -> dict[str, Any]:
        point_id = sample.get("测点编号")
        rule = next(
            (row for row in store.rows("alarm_trigger")
             if row.get("关联测点") == point_id and row.get("status") == "已启用"),
            None,
        )
        if rule is not None:
            return rule
        return self.alarm_rule()

    def confirm_sample(self, sample_ref: str | int) -> dict[str, Any]:
        sample = self.find_row(SAMPLE, sample_ref)
        if sample is None:
            return {"ok": False, "message": f"采样 {sample_ref} 不存在"}
        evaluation = self.evaluate_sample(sample_ref)
        if not evaluation.get("ok"):
            return evaluation
        result = evaluation["result"]
        if result["triggered"]:
            return {"ok": False, "triggered": True, "message": "当前系数判定已触发告警，不能按“不触发”确认", "result": result}
        sample["status"] = "已确认"
        sample["在途"] = False
        sample["confirmation_status"] = "已确认"
        sample["confirmed_at"] = now_iso()
        sample["confirmed_result_id"] = result["结果单号"]
        return {"ok": True, "triggered": False, "message": f"已确认原值 {sample['raw_value']:g} 不触发；历史版本和结果保留", "sample": sample, "result": result}

    def confirm_original_79(self) -> dict[str, Any]:
        self.ensure_seed()
        return self.confirm_sample("SR-HIST-79")


workflow = CalibrationWorkflow()


class CalibrationVerificationService(BaseModuleService):
    MODULE = VERIFICATION
    ENTITY = "探头检定行"
    LIST_FIELDS = [
        "检定行号", "批次号", "设备编号", "探头名称", "探头实际身份", "测点编号",
        "标准单位", "检定单位", "乘数", "偏移", "时段开始", "时段结束", "校验结果", "处理意见",
    ]
    REQUIRED_FIELDS = ["设备编号", "探头实际身份", "检定单位", "乘数", "偏移"]
    STATUS_ORDER = ["待办理", "校验通过", "已提交审批", "已退回"]
    ACTION_RULES = {"按行校验": "校验通过", "提交生效审批": "已提交审批"}

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        created = workflow.create_verification(values)
        row = created["row"]
        workflow.validate_verification(row["检定行号"])
        return row, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        row = store.find(self.MODULE, entry_id)
        if row is None:
            return None, f"检定行 {entry_id} 不存在"
        if action in ("按行校验", "校验"):
            result = workflow.validate_verification(row["检定行号"])
            return (result["row"], result["message"]) if result.get("ok") else (None, result["message"])
        if action in ("提交生效审批", "建立审批单"):
            result = workflow.create_approval(row["检定行号"])
            if not result.get("ok"):
                return None, result["message"]
            row["status"] = "已提交审批"
            return row, result["message"]
        return None, f"动作「{action}」不属于{self.MODULE}可执行范围"


class CalibrationApprovalService(BaseModuleService):
    MODULE = APPROVAL
    ENTITY = "校准生效审批单"
    LIST_FIELDS = [
        "审批单号", "检定行号", "设备编号", "探头名称", "探头实际身份",
        "系数版本", "乘数", "偏移", "时段开始", "时段结束", "conflict_status",
    ]
    REQUIRED_FIELDS = ["检定行号"]
    STATUS_ORDER = ["待审批", "已批准", "已生效"]
    ACTION_RULES = {"审批通过": "已批准", "审批通过并生效": "已生效", "处理冲突并重算": "已生效"}

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        row_ref = str(values.get("检定行号") or values.get("verification_id") or "").strip()
        if not row_ref:
            return None, ["检定行号"]
        result = workflow.create_approval(row_ref)
        if not result.get("ok"):
            return None, [result.get("message", "检定行不能建立审批单")]
        return result["approval"], []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"审批单 {entry_id} 不存在"
        result = workflow.run_approval_action(entry["审批单号"], action)
        if not result.get("ok"):
            return None, result.get("message", "审批动作失败")
        if "detail" in result:
            return result["detail"]["approval"], result["message"]
        return result.get("approval") or entry, result.get("message", "审批动作完成")


class SampleReadingService(BaseModuleService):
    MODULE = SAMPLE
    ENTITY = "采样读数"
    LIST_FIELDS = [
        "采样单号", "采样用途", "设备编号", "探头实际身份", "探头名称", "测点编号",
        "raw_value", "单位", "sampled_at", "coefficient_version", "multiplier", "offset",
        "calibrated_value", "threshold", "triggered", "status", "version_status",
    ]
    STATUS_ORDER = ["待确认", "已确认"]
    ACTION_RULES = {"确认读数": "已确认"}

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"采样读数 {entry_id} 不存在"
        if action in ("确认读数", "确认原值不触发"):
            result = workflow.confirm_sample(entry["采样单号"])
            if not result.get("ok"):
                return None, result["message"]
            return result["sample"], result["message"]
        return None, f"动作「{action}」不属于{self.MODULE}可执行范围"


class AlarmResultService(BaseModuleService):
    MODULE = RESULT
    ENTITY = "告警判定结果"
    LIST_FIELDS = [
        "结果单号", "alarm_event_id", "采样单号", "审批单号", "规则编号",
        "raw_value", "multiplier", "offset", "calibrated_value", "operator", "threshold",
        "triggered", "coefficient_version", "evaluated_at", "status", "message",
    ]
    STATUS_ORDER = ["未触发", "已触发告警"]


class ApprovalTodoService(BaseModuleService):
    MODULE = TODO
    ENTITY = "校准审批待办"
    LIST_FIELDS = ["待办单号", "审批单号", "类型", "标题", "status", "created_at", "completed_at", "处理结果"]
    STATUS_ORDER = ["待处理", "已完成"]
    ACTION_RULES = {"完成待办": "已完成"}

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"待办 {entry_id} 不存在"
        if action == "完成待办":
            entry["status"] = "已完成"
            entry["pending"] = False
            entry["completed_at"] = now_iso()
            return entry, "待办已完成"
        return None, f"动作「{action}」不属于{self.MODULE}可执行范围"
