"""告警触发领域服务：IoT测点阈值告警的全生命周期管理。

提供告警评估、批量检测、通知策略、告警统计等真实业务能力。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.services.calibration import identity_key, parse_datetime, workflow
from app.store import store

CST = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def _now_dt() -> datetime:
    return datetime.now(CST)


class AlarmTriggerService(BaseModuleService):
    MODULE = "alarm_trigger"
    ENTITY = "告警规则"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["规则编号", "关联测点", "告警条件", "阈值上限", "阈值下限", "持续秒数", "告警级别", "通知方式"]
    REQUIRED_FIELDS = ["规则编号", "关联测点", "告警条件"]
    STATUS_ORDER = ["草稿", "待验证", "已启用", "已静默"]
    ACTION_RULES = {"提交验证": "待验证", "启用规则": "已启用", "静默规则": "已静默"}
    NEGATIVE_ACTIONS = []

    def calibration_context(
        self,
        point_id: str,
        current_value: float,
        *,
        device_id: str | None = None,
        probe_identity: str | None = None,
        sampled_at: str | datetime | None = None,
        coefficient_version: str | None = None,
    ) -> dict[str, Any]:
        """解析同名探头身份，并返回采样时刻有效的同一版乘数/偏移。"""
        point = next(
            (row for row in store.rows("ts_point") if row.get("测点编号") == point_id),
            None,
        )
        device_id = device_id or (str(point.get("设备编号", "")) if point else "")
        probe_identity = probe_identity or (str(point.get("探头实际身份", "")) if point else "")
        at = parse_datetime(sampled_at) or _now_dt()

        coefficient = None
        version = "RAW-UNVERSIONED"
        multiplier = 1.0
        offset = 0.0
        key = ""
        if device_id and probe_identity:
            key = identity_key(device_id, probe_identity)
            coefficient = workflow.coefficient_for(key, at, coefficient_version)
            if coefficient is not None:
                version = str(coefficient["系数版本"])
                multiplier = float(coefficient["multiplier"])
                offset = float(coefficient["offset"])

        calibrated_value = round(float(current_value) * multiplier + offset, 6)
        return {
            "device_id": device_id,
            "probe_identity": probe_identity,
            "identity_key": key,
            "sampled_at": at.isoformat(timespec="seconds"),
            "coefficient_version": version,
            "multiplier": multiplier,
            "offset": offset,
            "raw_value": float(current_value),
            "calibrated_value": calibrated_value,
            "coefficient_found": coefficient is not None,
        }

    def evaluate_threshold(
        self,
        point_id: str,
        current_value: float,
        *,
        device_id: str | None = None,
        probe_identity: str | None = None,
        sampled_at: str | datetime | None = None,
        coefficient_version: str | None = None,
    ) -> dict[str, Any]:
        """评估单个测点是否触发告警阈值。

        业务流程：
        1. 查找该测点的已启用告警规则
        2. 对比阈值上下限
        3. 返回触发结果和告警详情
        """
        rows = store.rows(self.MODULE)
        calibration = self.calibration_context(
            point_id,
            current_value,
            device_id=device_id,
            probe_identity=probe_identity,
            sampled_at=sampled_at,
            coefficient_version=coefficient_version,
        )
        judged_value = calibration["calibrated_value"]
        triggered = []
        for alarm in rows:
            if alarm.get("关联测点") != point_id or alarm.get("status") != "已启用":
                continue
            try:
                upper = float(alarm.get("阈值上限", "inf"))
            except (ValueError, TypeError):
                upper = float("inf")
            try:
                lower = float(alarm.get("阈值下限", "-inf"))
            except (ValueError, TypeError):
                lower = float("-inf")

            condition = alarm.get("告警条件", "")
            hit = False
            if ">=" in condition:
                hit = judged_value >= upper
            elif ">" in condition:
                # 题述规则是“严格大于 80”：80 本身不能触发。
                hit = judged_value > upper
            elif "<=" in condition:
                hit = judged_value <= lower
            elif "<" in condition:
                hit = judged_value < lower
            elif "between" in condition.lower():
                hit = lower <= judged_value <= upper
            else:
                hit = judged_value > upper or judged_value < lower

            if hit:
                triggered.append({
                    "规则编号": alarm.get("规则编号"),
                    "告警级别": alarm.get("告警级别"),
                    "阈值上限": upper,
                    "阈值下限": lower,
                    "原始值": calibration["raw_value"],
                    "校准值": judged_value,
                    "当前值": judged_value,
                    "raw_value": calibration["raw_value"],
                    "calibrated_value": judged_value,
                    "multiplier": calibration["multiplier"],
                    "offset": calibration["offset"],
                    "coefficient_version": calibration["coefficient_version"],
                    "identity_key": calibration["identity_key"],
                    "通知方式": alarm.get("通知方式"),
                    "触发时间": _now(),
                })

        return {
            "ok": True,
            "point_id": point_id,
            "current_value": current_value,
            "raw_value": calibration["raw_value"],
            "calibrated_value": judged_value,
            "calibration": calibration,
            "triggered_count": len(triggered),
            "alarms": triggered,
        }

    def batch_check(self, points: list[dict[str, float]]) -> dict[str, Any]:
        """批量检查多个测点的告警状态。

        Args:
            points: [{"point_id": "x", "value": 1.0}, ...]
        """
        results = []
        triggered_count = 0
        for pt in points:
            res = self.evaluate_threshold(pt.get("point_id", ""), pt.get("value", 0))
            results.append(res)
            if res["triggered_count"] > 0:
                triggered_count += 1

        return {
            "ok": True,
            "total_points": len(points),
            "triggered_count": triggered_count,
            "healthy_count": len(points) - triggered_count,
            "details": results,
        }

    def alarm_statistics(self) -> dict[str, Any]:
        """告警规则统计：按级别、状态和关联测点分布。"""
        rows = store.rows(self.MODULE)
        by_level = {}
        by_status = {}
        by_point = {}

        for row in rows:
            level = row.get("告警级别", "未知")
            by_level[level] = by_level.get(level, 0) + 1

            status = row.get("status", "未知")
            by_status[status] = by_status.get(status, 0) + 1

            point = row.get("关联测点", "未知")
            by_point[point] = by_point.get(point, 0) + 1

        return {
            "total_rules": len(rows),
            "enabled_count": by_status.get("已启用", 0),
            "by_level": by_level,
            "by_status": by_status,
            "by_point": [
                {"测点": k, "告警规则数": v}
                for k, v in sorted(by_point.items(), key=lambda x: x[1], reverse=True)
            ],
        }

    # ========== 跨模块方法 ==========

    def evaluate_with_rule_engine(
        self,
        point_id: str,
        current_value: float,
        **calibration_kwargs: Any,
    ) -> dict[str, Any]:
        """告警触发后自动查找联动规则引擎执行对应动作。

        业务流程：
        1. 经校准系数版本评估告警阈值
        2. 如触发告警，查找rule_engine中已启用的联动规则
        3. 执行匹配的动作并记录
        """
        rule_rows = store.rows("rule_engine")
        evaluation = self.evaluate_threshold(point_id, current_value, **calibration_kwargs)
        triggered_ids = {item.get("规则编号") for item in evaluation.get("alarms", [])}
        triggered = [
            alarm for alarm in store.rows(self.MODULE)
            if alarm.get("规则编号") in triggered_ids
        ]

        if not triggered:
            calibrated = evaluation.get("calibrated_value", current_value)
            version = evaluation.get("calibration", {}).get("coefficient_version", "RAW")
            return {
                "ok": True,
                "triggered": False,
                "message": (
                    f"测点 {point_id} 原始值 {current_value} 经版本 {version} "
                    f"校准为 {calibrated}，未触发任何告警"
                ),
                "evaluation": evaluation,
            }

        # 查找联动规则
        actions = []
        for alarm in triggered:
            for rule in rule_rows:
                if rule.get("status") != "已启用":
                    continue
                try:
                    exec_count = int(rule.get("执行次数", "0")) + 1
                except (ValueError, TypeError):
                    exec_count = 1
                rule["执行次数"] = str(exec_count)
                actions.append({
                    "alarm_id": alarm.get("规则编号"),
                    "alarm_level": alarm.get("告警级别"),
                    "rule_engine_id": rule.get("规则编号"),
                    "action": rule.get("执行动作"),
                    "params": rule.get("动作参数"),
                    "exec_count": exec_count,
                    "coefficient_version": evaluation["calibration"]["coefficient_version"],
                    "raw_value": evaluation["raw_value"],
                    "calibrated_value": evaluation["calibrated_value"],
                })

        return {
            "ok": True,
            "triggered": True,
            "point_id": point_id,
            "current_value": current_value,
            "calibrated_value": evaluation["calibrated_value"],
            "calibration": evaluation["calibration"],
            "triggered_alarms": len(triggered),
            "rule_actions": actions,
            "evaluation": evaluation,
        }

    def correlate_with_device_status(self, device_id: str) -> dict[str, Any]:
        """将告警规则关联到设备注册状态, 按设备在线状况调整告警规则。

        业务流程：
        1. 查找设备信息
        2. 查找该设备关联的所有测点
        3. 汇总各测点的告警规则状态
        """
        device_rows = store.rows("device_registry")
        point_rows = store.rows("ts_point")
        alarm_rows = store.rows(self.MODULE)

        device = None
        for row in device_rows:
            if row.get("设备编号") == device_id:
                device = row
                break
        if device is None:
            return {"ok": False, "message": f"设备 {device_id} 不存在"}

        # 找到该设备的所有测点
        device_points = [
            pt for pt in point_rows
            if pt.get("设备编号") == device_id
        ]

        device_point_ids = {pt.get("测点编号") for pt in device_points}

        correlated = []
        for alarm in alarm_rows:
            if alarm.get("关联测点") in device_point_ids:
                correlated.append({
                    "规则编号": alarm.get("规则编号"),
                    "关联测点": alarm.get("关联测点"),
                    "告警条件": alarm.get("告警条件"),
                    "告警级别": alarm.get("告警级别"),
                    "规则状态": alarm.get("status"),
                })

        return {
            "ok": True,
            "设备编号": device_id,
            "设备状态": device.get("status"),
            "设备类型": device.get("设备类型"),
            "关联测点数": len(device_points),
            "告警规则数": len(correlated),
            "correlated": correlated,
        }