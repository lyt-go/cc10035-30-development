"""时序测点领域服务：IoT测点定义、采集管理和数据模拟。

提供测点配置、模拟数据生成、批量采集管理等真实业务能力。
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

CST = timezone(timedelta(hours=8))
random.seed(42)


def _now() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def _now_dt() -> datetime:
    return datetime.now(CST)


class TsPointService(BaseModuleService):
    MODULE = "ts_point"
    ENTITY = "测点定义"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["测点编号", "设备编号", "测点名称", "探头实际身份", "数据类型", "采集间隔", "上报方式", "单位符号", "量程范围"]
    REQUIRED_FIELDS = ["测点编号", "设备编号", "测点名称"]
    STATUS_ORDER = ["待配置", "采集中", "已停采", "已废弃"]
    ACTION_RULES = {"启动采集": "采集中", "停止采集": "已停采", "标记废弃": "已废弃"}
    NEGATIVE_ACTIONS = []

    def simulate_data(self, point_id: str, count: int = 10) -> dict[str, Any]:
        """模拟测点数据采集：根据测点配置生成模拟时序数据。

        业务流程：
        1. 查找测点定义
        2. 根据数据类型和量程范围生成模拟值
        3. 按采集间隔生成时间序列
        """
        rows = store.rows(self.MODULE)
        point = None
        for row in rows:
            if row.get("测点编号") == point_id:
                point = row
                break
        if point is None:
            return {"ok": False, "message": f"测点 {point_id} 不存在"}

        data_type = point.get("数据类型", "float64")
        range_str = point.get("量程范围", "0-100")
        try:
            parts = range_str.split("-")
            low = float(parts[0])
            high = float(parts[-1])
        except (ValueError, TypeError):
            low, high = 0, 100

        try:
            interval = int(point.get("采集间隔", "10").replace("s", ""))
        except (ValueError, TypeError):
            interval = 10

        # 生成模拟数据
        base = random.uniform(low, high)
        data_points = []
        now = _now_dt()
        for i in range(count):
            ts = (now - timedelta(seconds=interval * (count - i))).isoformat(timespec="seconds")
            # 叠加正弦波动模拟真实数据
            noise = random.uniform(-0.05, 0.05) * (high - low)
            wave = math.sin(i * 0.5) * (high - low) * 0.1
            if data_type in ("int32", "int64"):
                value = int(base + wave + noise)
            else:
                value = round(base + wave + noise, 3)
            data_points.append({"timestamp": ts, "value": value, "unit": point.get("单位符号", "")})

        return {
            "ok": True,
            "message": f"测点 {point_id} 模拟生成 {count} 条数据",
            "point_id": point_id,
            "device_id": point.get("设备编号"),
            "data_type": data_type,
            "interval_seconds": interval,
            "data": data_points,
        }

    def batch_collect_status(self) -> dict[str, Any]:
        """批量采集状态：统计各设备测点的采集情况。"""
        rows = store.rows(self.MODULE)
        by_device = {}
        by_status = {}
        for row in rows:
            dev = row.get("设备编号", "未知")
            if dev not in by_device:
                by_device[dev] = {"total": 0, "collecting": 0, "stopped": 0}
            by_device[dev]["total"] += 1
            if row.get("status") == "采集中":
                by_device[dev]["collecting"] += 1
            elif row.get("status") == "已停采":
                by_device[dev]["stopped"] += 1

            s = row.get("status", "未知")
            by_status[s] = by_status.get(s, 0) + 1

        return {
            "total_points": len(rows),
            "by_status": by_status,
            "by_device": [{"设备编号": k, **v} for k, v in by_device.items()],
            "collecting_rate": round(
                by_status.get("采集中", 0) / max(len(rows), 1) * 100, 1
            ),
        }