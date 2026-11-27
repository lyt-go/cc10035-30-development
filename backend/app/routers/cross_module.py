"""跨模块数据流统一接口：暴露9组数据流的操作端点。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.cross_module import cross_service

router = APIRouter(prefix="/api/cross", tags=["跨模块数据流"])


# ==================== Flow 1: 设备注册与协议适配 ====================

@router.post("/flow1/register")
def flow1_register_device(
    device_id: str = Query(..., description="设备编号"),
    device_type: str = Query(..., description="设备类型"),
    protocol_id: str = Query(..., description="协议配置编号"),
):
    """设备注册时自动绑定协议配置，校验协议状态。"""
    return cross_service.register_device_with_protocol(device_id, device_type, protocol_id)


@router.get("/flow1/status")
def flow1_device_protocol_status(device_id: str | None = None):
    """查询设备-协议关联状态矩阵。"""
    return {"data": cross_service.query_device_protocol_status(device_id)}


# ==================== Flow 2: 报文解码与消息路由 ====================

@router.post("/flow2/decode-route")
def flow2_decode_and_route(
    raw_message: str = Query(..., description="原始报文内容"),
    protocol_type: str = Query(..., description="协议类型"),
    topic: str = Query(..., description="源Topic"),
):
    """报文解码后按路由规则分发到目标Topic。"""
    return cross_service.decode_and_route(raw_message, protocol_type, topic)


# ==================== Flow 3: 时序测点与存储策略 ====================

@router.post("/flow3/configure")
def flow3_configure_point_store(
    point_id: str = Query(..., description="测点编号"),
    device_id: str = Query(..., description="设备编号"),
    point_name: str = Query(..., description="测点名称"),
    storage_engine: str = Query(..., description="存储引擎"),
):
    """为测点配置存储策略，自动关联设备档案。"""
    return cross_service.configure_point_with_store(point_id, device_id, point_name, storage_engine)


@router.get("/flow3/matrix")
def flow3_point_store_matrix():
    """查询测点-存储策略关联矩阵。"""
    return {"data": cross_service.query_point_store_matrix()}


# ==================== Flow 4: 降采样与断点补采 ====================

@router.post("/flow4/downsample")
def flow4_downsample_gap_check(
    source_point: str = Query(..., description="源测点"),
    target_granularity: str = Query(..., description="目标粒度"),
    agg_function: str = Query(..., description="聚合函数"),
    time_start: str | None = None,
    time_end: str | None = None,
):
    """降采样前先检查数据断点，存在断点则自动发起补采。"""
    return cross_service.downsample_with_gap_check(
        source_point, target_granularity, agg_function, time_start, time_end
    )


@router.post("/flow4/recovery")
def flow4_gap_recovery(
    device_id: str = Query(..., description="设备编号"),
    point_id: str = Query(..., description="测点编号"),
):
    """显式触发断点补采。"""
    return cross_service.trigger_gap_recovery(device_id, point_id)


# ==================== Flow 5: 告警触发与联动规则 ====================

@router.post("/flow5/evaluate")
def flow5_evaluate_alarm(
    point_id: str = Query(..., description="测点编号"),
    current_value: float = Query(..., description="当前值"),
    device_id: str | None = Query(default=None, description="设备编号，用于同名探头隔离"),
    probe_identity: str | None = Query(default=None, description="探头实际身份/序列号"),
    sampled_at: str | None = Query(default=None, description="采样时间 ISO8601"),
):
    """当测点值触发告警时，自动执行关联的联动规则。"""
    return cross_service.evaluate_alarm_with_rule(
        point_id,
        current_value,
        device_id=device_id,
        probe_identity=probe_identity,
        sampled_at=sampled_at,
    )


# ==================== Flow 6: 设备影子与标签绑定 ====================

@router.post("/flow6/sync-shadow")
def flow6_sync_shadow_tags(
    device_id: str = Query(..., description="设备编号"),
    desired_state: str = Query(..., description="期望状态"),
):
    """设备影子同步时自动关联标签。"""
    return cross_service.sync_device_shadow_with_tags(device_id, desired_state)


@router.post("/flow6/bind-tag")
def flow6_bind_tag_shadow(
    device_id: str = Query(..., description="设备编号"),
    tag_key: str = Query(..., description="标签键"),
    tag_value: str = Query(..., description="标签值"),
):
    """绑定标签时校验设备影子状态。"""
    return cross_service.bind_tag_with_shadow_check(device_id, tag_key, tag_value)


# ==================== Flow 7: 网关管理与边缘缓存 ====================

@router.post("/flow7/cache")
def flow7_gateway_cache(
    gateway_id: str = Query(..., description="网关编号"),
    cache_size: str = Query(default="256MB", description="缓存大小"),
    eviction_strategy: str = Query(default="LRU", description="淘汰策略"),
):
    """管理网关边缘缓存配置。"""
    return cross_service.manage_gateway_cache(gateway_id, cache_size, eviction_strategy)


@router.get("/flow7/matrix")
def flow7_gateway_cache_matrix():
    """查询网关-缓存关联矩阵。"""
    return {"data": cross_service.query_gateway_cache_matrix()}


# ==================== Flow 8: 固件升级与聚合分发 ====================

@router.post("/flow8/ota-dispatch")
def flow8_ota_aggregate(
    target_device: str = Query(..., description="目标设备"),
    firmware_version: str = Query(..., description="固件版本"),
    upgrade_strategy: str = Query(default="rolling", description="升级策略"),
    target_count: int = Query(default=10, description="目标设备数"),
):
    """固件升级任务创建后，自动创建聚合分发任务。"""
    return cross_service.ota_with_aggregate_dispatch(
        target_device, firmware_version, upgrade_strategy, target_count
    )


@router.get("/flow8/status")
def flow8_ota_aggregate_status(ota_task_id: str | None = None):
    """查询固件升级与聚合分发关联状态。"""
    return {"data": cross_service.query_ota_aggregate_status(ota_task_id)}


# ==================== Flow 9: 数据流管道与批量导出 ====================

@router.post("/flow9/export")
def flow9_stream_export(
    stream_id: str = Query(..., description="管道编号"),
    device_range: str = Query(..., description="设备范围"),
    point_list: str = Query(..., description="测点列表"),
    time_start: str | None = None,
    time_end: str | None = None,
    export_format: str = Query(default="CSV", description="导出格式"),
):
    """从数据流管道触发批量导出。"""
    return cross_service.stream_to_batch_export(
        stream_id, device_range, point_list, time_start, time_end, export_format
    )


@router.get("/flow9/matrix")
def flow9_stream_export_matrix():
    """查询数据流管道与批量导出关联矩阵。"""
    return {"data": cross_service.query_stream_export_matrix()}


# ==================== 跨模块概览 ====================

@router.get("/overview")
def cross_overview():
    """跨模块数据流总览。"""
    return cross_service.cross_module_overview()