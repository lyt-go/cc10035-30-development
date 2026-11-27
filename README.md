# IoT设备数据接入与协议适配平台

面向IoT设备注册、多协议适配、消息路由与时序数据归集的设备数据接入平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 设备注册 | `device_registry` | 设备档案 | 设备编号、设备类型、协议类型 |
| 协议配置 | `protocol_cfg` | 协议配置 | 配置编号、协议名称、传输方式 |
| 报文解码 | `msg_decode` | 解码规则 | 规则编号、协议类型、报文标识 |
| 消息路由 | `msg_router` | 路由规则 | 规则编号、匹配Topic、目标Topic |
| 时序测点 | `ts_point` | 测点定义 | 测点编号、设备编号、测点名称 |
| 时序存储 | `ts_store` | 存储策略 | 策略编号、测点编号、存储引擎 |
| 降采样 | `downsample` | 降采样任务 | 任务编号、源测点、目标粒度 |
| 告警触发 | `alarm_trigger` | 告警规则 | 规则编号、关联测点、告警条件 |
| 固件升级 | `firmware_ota` | 升级任务 | 任务编号、目标设备、固件版本 |
| 网关管理 | `gateway_mgmt` | 网关节点 | 网关编号、网关地址、挂载设备数 |
| 设备影子 | `shadow_dev` | 影子记录 | 记录编号、设备编号、期望状态 |
| 数据断点 | `data_gap` | 断点记录 | 记录编号、设备编号、测点编号 |
| 批量导出 | `batch_export` | 导出任务 | 任务编号、设备范围、测点列表 |
| 规则引擎 | `rule_engine` | 联动规则 | 规则编号、触发条件、执行动作 |
| 边缘缓存 | `edge_cache` | 缓存配置 | 配置编号、网关编号、缓存大小 |
| 标签绑定 | `tag_binding` | 标签关系 | 关系编号、设备编号、标签键 |
| 数据流管道 | `data_stream` | 流管道 | 管道编号、输入源、处理算子链 |
| 聚合分发 | `aggregate_sink` | 分发任务 | 任务编号、数据窗口、聚合函数 |

## 探头校准生效审批

侧栏「校准生效审批」提供题述闭环，也可从「时序测点」或「告警触发」页顶部入口进入：

1. `ALARM-CAL-80` 为严格 `> 80` 规则；先确认 `SR-HIST-79` 在 V1（乘数 1、偏移 0）下为 79，不触发。
2. `CAL-BATCH-001` 含两行：`CAL-VER-OFFSET2` 是单位 ℃、乘数 1、偏移 +2 的合格行；`CAL-VER-BAD-UNIT` 是错单位行。点击「按行办理」后，错单位行单独退回，不替换 V1，也不阻止合格行建单。
3. 从 `CAL-VER-OFFSET2` 建立 `CAL-APR-0001` 并「审批通过并发布生效」。系统检测到未确认的在途读数 `SR-INFLIGHT-79` 与 V2 时段相交，记录版本冲突和待办；告警服务立即用同一 `CAL-COEF-V2` 的乘数 1 与偏移 2 计算 `79 × 1 + 2 = 81`，严格大于 80，因此触发。
4. 在生效审批详情页可通过锚点回查待办、告警结果、原始值/乘数/偏移/校准值/系数版本对应关系和完整留证；确认后关闭冲突待办。已确认的 `SR-HIST-79` 保留 V1 的 79 判定，仍可在 `sample_reading`、`alarm_result` 或校准工作台查询。

同名探头使用 `设备编号::探头实际身份` 作为身份键，不按探头名称关联系数。主要聚合接口：

- `GET /api/calibration/scenario` / `POST /api/calibration/scenario/reset`
- `POST /api/calibration/original-reading/confirm`
- `POST /api/calibration/verification/process`
- `POST /api/calibration/verification/{行号}/submit`
- `POST /api/calibration/approvals/{单号}/approve-and-activate`
- `GET /api/calibration/approvals/{单号}`
- `POST /api/calibration/approvals/{单号}/resolve-conflict`

检定行、审批单、采样、告警结果和待办也分别注册为 `calibration_verification`、`calibration_approval`、`sample_reading`、`alarm_result`、`approval_todo` 通用资源。

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数据采集、爬虫与RPA
