<template>
  <section class="page approval-detail-page" data-testid="approval-detail">
    <header class="page-head">
      <div>
        <RouterLink class="back-link" to="/calibration">← 返回校准工作台</RouterLink>
        <h2>生效审批详情页：{{ approvalId }}</h2>
        <p class="page-desc">从检定行到告警动作的审批、版本冲突、待办和触发数值均在此留证。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" :disabled="busy" @click="load">刷新留证</button>
        <button
          v-if="approval && approval.status !== '已生效'"
          class="btn primary"
          type="button"
          data-testid="approve-and-activate"
          :disabled="busy"
          @click="approveAndActivate"
        >
          审批通过并发布生效
        </button>
      </div>
    </header>

    <div v-if="message" class="inline-message" data-testid="detail-message">{{ message }}</div>
    <div v-if="errorMessage" class="inline-error" data-testid="detail-error">{{ errorMessage }}</div>
    <div v-if="loading" class="panel">正在读取审批留证…</div>
    <div v-else-if="!approval" class="panel" data-testid="approval-not-found">
      <h3>审批单尚未建立或不存在</h3>
      <p>请先在校准工作台的合格检定行 <code>CAL-VER-OFFSET2</code> 上建立审批单。</p>
      <RouterLink class="btn primary" to="/calibration">前往校准工作台</RouterLink>
    </div>

    <template v-else>
      <div class="stat-row">
        <article class="stat-card"><span class="stat-label">审批状态</span><strong class="stat-value" data-testid="approval-status">{{ approval.status }}</strong></article>
        <article class="stat-card"><span class="stat-label">系数版本</span><strong class="stat-value">{{ approval['系数版本'] }}</strong></article>
        <article class="stat-card"><span class="stat-label">冲突状态</span><strong class="stat-value">{{ approval.conflict_status }}</strong></article>
        <article class="stat-card"><span class="stat-label">告警结果数</span><strong class="stat-value">{{ alarmResults.length }}</strong></article>
      </div>

      <nav class="trace-bar panel" data-testid="trace-links">
        <strong>从本单回查：</strong>
        <a
          v-for="todo in todos"
          :key="todo['待办单号']"
          :href="`#todo-${todo['待办单号']}`"
          class="trace-link"
          :data-testid="`trace-todo-${todo['待办单号']}`"
        >
          待办 {{ todo['待办单号'] }}（{{ todo.status }}）
        </a>
        <a
          v-for="result in alarmResults"
          :key="result['结果单号']"
          :href="`#alarm-${result['结果单号']}`"
          class="trace-link alarm"
          :data-testid="`trace-alarm-${result['结果单号']}`"
        >
          告警结果 {{ result['结果单号'] }}（{{ result.triggered ? '已触发' : '未触发' }}）
        </a>
        <span v-if="!todos.length && !alarmResults.length" class="muted">暂无关联待办和告警结果</span>
      </nav>

      <div v-if="hasOpenConflict" class="conflict-banner" data-testid="version-conflict">
        <h3>生效到达时发生版本冲突</h3>
        <p>
          审批系数 <strong>{{ approval['系数版本'] }}</strong> 已生效，但以下在途采样曾固化旧版本。
          系统不会把一个版本的乘数与另一个版本的偏移混用；告警服务已使用同一新版本的两项系数完成预演，
          请核对下方告警结果后确认并关闭待办。
        </p>
        <ul>
          <li v-for="sample in conflictSamples" :key="sample['采样单号']">
            <strong>{{ sample['采样单号'] }}</strong>：原始值 {{ sample.raw_value }}，
            到达前版本
            <strong data-testid="conflict-old-version">
              {{ sample.pre_conflict_snapshot?.coefficient_version ?? sample.coefficient_version }}
            </strong>
            （旧判定值 {{ sample.pre_conflict_snapshot?.calibrated_value ?? sample.calibrated_value }}），
            状态 {{ sample.version_status }}
          </li>
        </ul>
        <button
          class="btn primary danger"
          type="button"
          data-testid="resolve-conflict"
          :disabled="busy"
          @click="resolveConflict"
        >
          按同一 {{ approval?.['系数版本'] }} 版本重算并确认结果、关闭待办
        </button>
      </div>

      <div class="grid-two">
        <article class="panel" data-testid="source-verification">
          <h3>检定行</h3>
          <template v-if="verificationRow">
            <dl class="kv">
              <dt>检定行号</dt><dd>{{ verificationRow['检定行号'] }}</dd>
              <dt>批次号</dt><dd>{{ verificationRow['批次号'] }}</dd>
              <dt>设备 / 实际身份</dt><dd>{{ verificationRow['设备编号'] }} / {{ verificationRow['探头实际身份'] }}</dd>
              <dt>探头名称</dt><dd>{{ verificationRow['探头名称'] }}（同名不影响身份隔离）</dd>
              <dt>单位</dt><dd>{{ verificationRow['检定单位'] }} / 标准 {{ verificationRow['标准单位'] }}</dd>
              <dt>原始系数</dt><dd>{{ verificationRow['乘数'] }} / {{ verificationRow['偏移'] }}</dd>
              <dt>校验意见</dt><dd>{{ verificationRow['处理意见'] }}</dd>
            </dl>
          </template>
          <p v-else class="muted">未找到来源检定行。</p>
        </article>

        <article class="panel" data-testid="coefficient-evidence">
          <h3>获准时段的同一系数版本</h3>
          <template v-if="coefficient">
            <dl class="kv">
              <dt>版本</dt><dd data-testid="coefficient-version">{{ coefficient['系数版本'] }}</dd>
              <dt>身份键</dt><dd><code>{{ coefficient.identity_key }}</code></dd>
              <dt>乘数 multiplier</dt><dd data-testid="coefficient-multiplier">{{ coefficient.multiplier }}</dd>
              <dt>偏移 offset</dt><dd data-testid="coefficient-offset">+{{ coefficient.offset }}</dd>
              <dt>有效时段</dt><dd>{{ coefficient.valid_start }} 至 {{ coefficient.valid_end }}</dd>
              <dt>状态</dt><dd>{{ coefficient.status }}</dd>
              <dt>告警动作</dt><dd data-testid="alarm-action-link">{{ approval.alarm_action }}</dd>
            </dl>
          </template>
          <p v-else class="muted">系数版本尚未生成。</p>
        </article>
      </div>

      <article class="panel" data-testid="todo-panel">
        <h3>待办回查</h3>
        <div v-if="!todos.length" class="empty-state">审批单建立后会生成待办。</div>
        <div
          v-for="todo in todos"
          :id="`todo-${todo['待办单号']}`"
          :key="todo['待办单号']"
          class="evidence-card todo-card"
          :data-testid="`todo-${todo['待办单号']}`"
          :data-status="todo.status"
        >
          <div class="card-title">
            <strong>{{ todo['待办单号'] }}</strong>
            <span class="status-pill" :data-testid="`todo-status-${todo['待办单号']}`">{{ todo.status }}</span>
          </div>
          <p>{{ todo['标题'] }}</p>
          <p class="muted">类型：{{ todo['类型'] }}；创建：{{ todo.created_at }}；完成：{{ todo.completed_at || '未完成' }}</p>
          <p v-if="todo['处理结果']"><strong>处理结果：</strong>{{ todo['处理结果'] }}</p>
        </div>
      </article>

      <article class="panel" data-testid="alarm-panel">
        <h3>告警结果与触发数值版本对应</h3>
        <div v-if="!alarmResults.length" class="empty-state">处理版本冲突后，这里会显示 79 × 1 + 2 = 81 的严格大于 80 判定。</div>
        <div
          v-for="result in alarmResults"
          :id="`alarm-${result['结果单号']}`"
          :key="result['结果单号']"
          class="evidence-card alarm-card"
          :data-testid="`alarm-result-${result['结果单号']}`"
          :data-result-id="result['结果单号']"
          :data-raw="result.raw_value"
          :data-multiplier="result.multiplier"
          :data-offset="result.offset"
          :data-calibrated="result.calibrated_value"
          :data-version="result.coefficient_version"
          :data-triggered="String(result.triggered)"
        >
          <div class="card-title">
            <strong>{{ result['结果单号'] }} / {{ result.alarm_event_id }}</strong>
            <span :class="result.triggered ? 'trigger-pill' : 'safe-pill'">{{ result.triggered ? '已触发告警' : '未触发' }}</span>
          </div>
          <p class="formula" data-testid="trigger-formula">
            原始值 <strong data-testid="used-raw">{{ result.raw_value }}</strong>
            × 同版乘数 <strong data-testid="used-multiplier">{{ result.multiplier }}</strong>
            + 同版偏移 <strong data-testid="used-offset">{{ result.offset }}</strong>
            = 校准值 <strong class="calibrated" data-testid="used-calibrated">{{ result.calibrated_value }}</strong>
            ；规则 <strong>{{ result.operator }} {{ result.threshold }}</strong>
          </p>
          <p>
            使用版本：<strong data-testid="used-version">{{ result.coefficient_version }}</strong>
            （乘数与偏移均来自该版本：{{ result.coefficient_fields?.multiplier_from_same_version }} /
            {{ result.coefficient_fields?.offset_from_same_version }}）
          </p>
          <p class="muted">采样：{{ result['采样单号'] }}；规则：{{ result['规则编号'] }}；时间：{{ result.evaluated_at }}</p>
          <p>{{ result.message }}</p>
        </div>
      </article>

      <article class="panel" data-testid="evidence-timeline">
        <h3>审批留证时间线</h3>
        <ol class="timeline">
          <li v-for="(event, index) in evidence" :key="index" :data-testid="`evidence-${event.type}`">
            <time>{{ event.at }}</time>
            <strong>{{ event.type }}</strong>
            <span>{{ event.message }}</span>
          </li>
        </ol>
      </article>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import {
  approveAndActivateApproval,
  getCalibrationApproval,
  resolveApprovalConflict,
} from '@/api/backend-service'

const props = defineProps<{ approvalId: string }>()
type Row = Record<string, any>

const detail = ref<Row | null>(null)
const loading = ref(true)
const busy = ref(false)
const message = ref('')
const errorMessage = ref('')

const approval = computed<Row | null>(() => detail.value?.approval ?? null)
const verificationRow = computed<Row | null>(() => detail.value?.verification_row ?? null)
const coefficient = computed<Row | null>(() => detail.value?.coefficient ?? null)
const todos = computed<Row[]>(() => detail.value?.todos ?? [])
const alarmResults = computed<Row[]>(() => detail.value?.alarm_results ?? [])
const conflictSamples = computed<Row[]>(() => detail.value?.conflict_samples ?? [])
const evidence = computed<Row[]>(() => detail.value?.evidence ?? approval.value?.evidence ?? [])
const hasOpenConflict = computed(() => String(approval.value?.conflict_status ?? '').includes('待处理'))

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    detail.value = await getCalibrationApproval(props.approvalId)
  } catch (error) {
    detail.value = null
    errorMessage.value = error instanceof Error ? error.message : '审批详情读取失败'
  } finally {
    loading.value = false
  }
}

function adoptResult(result: Row, fallback: string) {
  if (result.ok === false) {
    errorMessage.value = String(result.message ?? '操作失败')
    message.value = ''
    if (result.detail) detail.value = result.detail
  } else {
    message.value = String(result.message ?? fallback)
    errorMessage.value = ''
    if (result.detail) detail.value = result.detail
  }
}

async function approveAndActivate() {
  busy.value = true
  errorMessage.value = ''
  try {
    const result = await approveAndActivateApproval(props.approvalId)
    adoptResult(result, '审批已生效')
    await load()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '审批生效失败'
  } finally {
    busy.value = false
  }
}

async function resolveConflict() {
  busy.value = true
  errorMessage.value = ''
  try {
    const result = await resolveApprovalConflict(props.approvalId)
    adoptResult(result, '冲突已按同一版本处理')
    if (result.detail) detail.value = result.detail
    await load()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '冲突处理失败'
  } finally {
    busy.value = false
  }
}

watch(() => props.approvalId, load)
onMounted(load)
</script>

<style scoped>
.back-link { color: var(--brand); text-decoration: none; font-size: 13px; }
.approval-detail-page { display: flex; flex-direction: column; gap: 14px; }
.panel { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
.grid-two { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 14px; }
.trace-bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.trace-link { padding: 4px 8px; border-radius: 999px; background: #eef4ff; color: #175cd3; text-decoration: none; font-size: 13px; }
.trace-link.alarm { background: #fff1f3; color: #b42318; }
.conflict-banner { border: 1px solid #f79009; background: #fffaeb; border-radius: 10px; padding: 14px; }
.conflict-banner h3 { margin-top: 0; color: #b54708; }
.inline-message, .inline-error { padding: 10px 12px; border-radius: 8px; }
.inline-message { background: #ecfdf3; border: 1px solid #86efac; color: #027a48; }
.inline-error { background: #fef3f2; border: 1px solid #fda29b; color: #b42318; }
.kv { display: grid; grid-template-columns: 130px 1fr; gap: 8px; margin: 0; font-size: 13px; }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; }
.evidence-card { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; }
.card-title { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.status-pill, .trigger-pill, .safe-pill { border-radius: 999px; padding: 2px 10px; font-size: 12px; }
.status-pill { background: #eef2f6; color: #344054; }
.trigger-pill { background: #fee4e2; color: #b42318; font-weight: 700; }
.safe-pill { background: #dcfae6; color: #027a48; }
.formula { font-size: 15px; }
.calibrated { color: #b42318; font-size: 18px; }
.timeline { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 10px; }
.timeline li { display: grid; grid-template-columns: 170px 110px 1fr; gap: 10px; align-items: start; border-left: 3px solid var(--brand); padding-left: 10px; font-size: 13px; }
.timeline time { color: var(--muted); }
.btn.danger { background: #d92d20; border-color: #d92d20; }
.muted { color: var(--muted); font-size: 12px; }
</style>
