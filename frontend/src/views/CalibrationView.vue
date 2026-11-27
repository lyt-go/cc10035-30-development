<template>
  <section class="page calibration-page" data-testid="calibration-workspace">
    <header class="page-head">
      <div>
        <h2>探头检定 → 校准生效审批 → 告警留证</h2>
        <p class="page-desc">
          时序测点不再只按原始值判断：告警服务只消费获准时段内、同一系数版本的乘数与偏移；
          同名探头按“设备编号 + 探头实际身份”隔离。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn ghost" data-testid="reset-scenario" type="button" :disabled="busy" @click="reset">
          重置题述场景
        </button>
        <RouterLink class="btn primary" to="/calibration/approvals/CAL-APR-0001">
          打开题述审批详情
        </RouterLink>
      </div>
    </header>

    <div v-if="message" class="inline-message" data-testid="workflow-message">{{ message }}</div>
    <div v-if="errorMessage" class="inline-error" data-testid="workflow-error">{{ errorMessage }}</div>

    <div class="grid-two">
      <article class="panel" data-testid="threshold-rule">
        <h3>1. 严格阈值规则</h3>
        <form class="rule-form" @submit.prevent="saveRule">
          <label>
            比较符
            <select v-model="ruleOperator" data-testid="rule-operator">
              <option value=">">严格大于 &gt;</option>
              <option value=">=">大于等于 &ge;</option>
              <option value="<">严格小于 &lt;</option>
            </select>
          </label>
          <label>
            阈值
            <input v-model="ruleThreshold" inputmode="decimal" data-testid="rule-threshold" />
          </label>
          <button class="btn primary" type="submit" :disabled="busy" data-testid="save-threshold">设置并启用</button>
        </form>
        <p><strong>{{ rule['规则编号'] ?? 'ALARM-CAL-80' }}</strong>：{{ rule['告警条件'] ?? '严格大于（>）' }} {{ rule['阈值上限'] ?? 80 }}</p>
        <p class="muted">边界 80 不触发；原值 79 在乘数 1、偏移 0 时不触发；生效偏移 +2 后按 81 判定并触发。</p>
      </article>

      <article class="panel" data-testid="identity-policy">
        <h3>身份与版本规则</h3>
        <p>身份键：<code>设备编号::探头实际身份</code>，不使用探头名称。</p>
        <p>采样记录固化同一版本的 <code>multiplier</code> 与 <code>offset</code>；已确认历史读数和判定不被覆盖。</p>
      </article>
    </div>

    <article class="panel">
      <div class="panel-head">
        <h3>2. 先确认原值 79 不触发</h3>
        <button class="btn primary" data-testid="confirm-original-79" type="button" :disabled="busy" @click="confirmOriginal">
          确认原值 79 不触发
        </button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>采样单号</th><th>用途</th><th>原始值</th><th>版本</th><th>乘数</th><th>偏移</th>
            <th>判定值</th><th>状态</th><th>版本状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="sample in samples" :key="sample['采样单号']" :data-testid="`sample-row-${sample['采样单号']}`">
            <td>{{ sample['采样单号'] }}</td>
            <td>{{ sample['采样用途'] }}</td>
            <td>{{ sample.raw_value }}</td>
            <td>{{ sample.coefficient_version }}</td>
            <td>{{ sample.multiplier }}</td>
            <td>{{ sample.offset }}</td>
            <td>{{ sample.calibrated_value }}</td>
            <td>{{ sample.status }}</td>
            <td :class="{ conflict: sample.version_conflict }">{{ sample.version_status }}</td>
          </tr>
        </tbody>
      </table>
    </article>

    <article class="panel">
      <div class="panel-head">
        <h3>3. 探头检定表（非法单位/数值按行退回，不阻止合法行）</h3>
        <button class="btn primary" data-testid="process-batch" type="button" :disabled="busy" @click="processBatch">
          按行办理 CAL-BATCH-001
        </button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>检定行号</th><th>设备/实际身份</th><th>同名探头</th><th>单位</th><th>乘数</th><th>偏移</th>
            <th>有效时段</th><th>状态与退回原因</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in verifications"
            :key="row['检定行号']"
            :data-testid="`verification-row-${row['检定行号']}`"
            :data-status="row.status"
            :data-valid="row['校验结果']"
          >
            <td>{{ row['检定行号'] }}</td>
            <td>{{ row['设备编号'] }}<br><small>{{ row['探头实际身份'] }}</small></td>
            <td>{{ row['探头名称'] }}</td>
            <td :class="{ invalid: row['检定单位'] === 'V' }">{{ row['检定单位'] }}</td>
            <td>{{ row['乘数'] }}</td>
            <td>{{ row['偏移'] }}</td>
            <td><small>{{ row['时段开始'] }}<br>至 {{ row['时段结束'] }}</small></td>
            <td>
              <strong>{{ row.status }}</strong>
              <p class="row-reason" :data-testid="`verification-message-${row['检定行号']}`">{{ row['处理意见'] || '尚未按行办理' }}</p>
            </td>
            <td>
              <button
                v-if="row['校验结果'] === '合格'"
                class="link"
                type="button"
                :data-testid="`create-approval-${row['检定行号']}`"
                :disabled="busy"
                @click="createApproval(row['检定行号'])"
              >
                建立生效审批单
              </button>
              <span v-else class="muted">合格后可建单</span>
            </td>
          </tr>
        </tbody>
      </table>

      <form class="inline-form" data-testid="add-verification-row" @submit.prevent="addInvalidNumericRow">
        <strong>追加一行非法数值用于验证按行退回：</strong>
        <label>设备 <input v-model="newRow['设备编号']" data-testid="new-row-device"></label>
        <label>实际身份 <input v-model="newRow['探头实际身份']" data-testid="new-row-identity"></label>
        <label>单位 <input v-model="newRow['检定单位']" data-testid="new-row-unit"></label>
        <label>乘数 <input v-model="newRow['乘数']" data-testid="new-row-multiplier"></label>
        <label>偏移 <input v-model="newRow['偏移']" data-testid="new-row-offset"></label>
        <button class="btn" type="submit" :disabled="busy" data-testid="submit-invalid-row">追加并按行校验</button>
      </form>
    </article>

    <article class="panel">
      <h3>4. 生效审批单与详情留证</h3>
      <div v-if="!approvals.length" class="empty-state">尚未建单；请先在合格检定行上点击“建立生效审批单”。</div>
      <table v-else class="data-table">
        <thead>
          <tr><th>审批单号</th><th>检定行</th><th>身份键</th><th>版本</th><th>系数</th><th>状态</th><th>冲突</th><th>详情</th></tr>
        </thead>
        <tbody>
          <tr v-for="approval in approvals" :key="approval['审批单号']" :data-testid="`approval-row-${approval['审批单号']}`">
            <td>{{ approval['审批单号'] }}</td>
            <td>{{ approval['检定行号'] }}</td>
            <td><small>{{ approval.identity_key }}</small></td>
            <td>{{ approval['系数版本'] }}</td>
            <td>{{ approval['乘数'] }} / {{ approval['偏移'] }}</td>
            <td>{{ approval.status }}</td>
            <td>{{ approval.conflict_status }}</td>
            <td>
              <RouterLink
                class="link"
                :to="`/calibration/approvals/${approval['审批单号']}`"
                :data-testid="`approval-link-${approval['审批单号']}`"
              >
                打开生效审批详情页
              </RouterLink>
            </td>
          </tr>
        </tbody>
      </table>
    </article>

    <div class="grid-two">
      <article class="panel" data-testid="identity-isolation">
        <h3>同名探头隔离系数</h3>
        <table class="data-table compact">
          <thead><tr><th>身份键</th><th>版本</th><th>乘数</th><th>偏移</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="coef in coefficients" :key="coef['系数版本']">
              <td><small>{{ coef.identity_key }}</small></td>
              <td>{{ coef['系数版本'] }}</td><td>{{ coef.multiplier }}</td><td>{{ coef.offset }}</td><td>{{ coef.status }}</td>
            </tr>
          </tbody>
        </table>
      </article>

      <article class="panel" data-testid="historical-results">
        <h3>已确认历史读数与告警判定仍可查询</h3>
        <table class="data-table compact">
          <thead><tr><th>结果号</th><th>采样</th><th>原始→校准</th><th>版本</th><th>触发</th></tr></thead>
          <tbody>
            <tr v-for="item in alarmResults" :key="item['结果单号']" :data-testid="`historical-result-${item['结果单号']}`">
              <td>{{ item['结果单号'] }}</td>
              <td>{{ item['采样单号'] }}</td>
              <td>{{ item.raw_value }} → {{ item.calibrated_value }}</td>
              <td>{{ item.coefficient_version }}</td>
              <td>{{ item.triggered ? '是' : '否' }}</td>
            </tr>
            <tr v-if="!alarmResults.length"><td colspan="5" class="empty-state">暂无判定记录</td></tr>
          </tbody>
        </table>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  confirmOriginalReading,
  getCalibrationScenario,
  processVerificationBatch,
  processVerificationRows,
  resetCalibrationScenario,
  saveCalibrationRule,
  submitVerificationRow,
} from '@/api/backend-service'

type Row = Record<string, any>

const scenario = ref<Row>({})
const busy = ref(false)
const message = ref('')
const errorMessage = ref('')
const ruleOperator = ref('>')
const ruleThreshold = ref('80')
const newRow = ref<Record<string, string>>({
  设备编号: 'DEVI-0001',
  探头实际身份: 'PRB-A-0001',
  探头名称: '温度探头',
  测点编号: 'TS_P-CAL-80',
  标准单位: '℃',
  检定单位: '℃',
  乘数: 'not-a-number',
  偏移: '2',
  批次号: 'CAL-BATCH-INVALID',
})

const rule = computed<Row>(() => scenario.value.rule ?? {})
const verifications = computed<Row[]>(() => scenario.value.verifications ?? [])
const approvals = computed<Row[]>(() => scenario.value.approvals ?? [])
const coefficients = computed<Row[]>(() => scenario.value.coefficients ?? [])
const samples = computed<Row[]>(() => scenario.value.samples ?? [])
const alarmResults = computed<Row[]>(() => scenario.value.alarm_results ?? [])

function showResult(result: Row, successFallback: string) {
  if (result.ok === false) {
    errorMessage.value = String(result.message ?? '操作失败')
    message.value = ''
  } else {
    message.value = String(result.message ?? successFallback)
    errorMessage.value = ''
  }
}

async function load() {
  try {
    scenario.value = await getCalibrationScenario()
    ruleOperator.value = String(rule.value.operator ?? '>')
    ruleThreshold.value = String(rule.value['阈值'] ?? rule.value['阈值上限'] ?? '80')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '校准场景读取失败'
  }
}

async function saveRule() {
  busy.value = true
  try {
    const threshold = Number(ruleThreshold.value)
    const result = await saveCalibrationRule(threshold, ruleOperator.value)
    showResult(result, '严格阈值已保存')
    await load()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '阈值保存失败'
  } finally {
    busy.value = false
  }
}

async function reset() {
  busy.value = true
  try {
    scenario.value = await resetCalibrationScenario()
    ruleOperator.value = '>'
    ruleThreshold.value = '80'
    message.value = '题述场景已重置：原值 79、合格 +2 行、错单位行和在途读数均已恢复'
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '场景重置失败'
  } finally {
    busy.value = false
  }
}

async function confirmOriginal() {
  busy.value = true
  try {
    const result = await confirmOriginalReading()
    showResult(result, '原值 79 确认不触发')
    await load()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '原值确认失败'
  } finally {
    busy.value = false
  }
}

async function processBatch() {
  busy.value = true
  try {
    const result = await processVerificationBatch('CAL-BATCH-001')
    showResult(result, '按行办理完成')
    await load()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '按行办理失败'
  } finally {
    busy.value = false
  }
}

async function createApproval(rowId: string) {
  busy.value = true
  try {
    const result = await submitVerificationRow(rowId)
    showResult(result, '审批单已建立')
    await load()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '审批单建立失败'
  } finally {
    busy.value = false
  }
}

async function addInvalidNumericRow() {
  busy.value = true
  try {
    const result = await processVerificationRows([{ ...newRow.value }])
    showResult(result, '非法数值行已按行退回')
    await load()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '追加检定行失败'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.calibration-page { display: flex; flex-direction: column; gap: 14px; }
.grid-two { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 14px; }
.rule-form { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; margin-bottom: 10px; }
.rule-form label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.rule-form input, .rule-form select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; min-width: 120px; }
.panel { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
.panel h3 { margin: 0 0 10px; font-size: 16px; }
.panel-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 10px; }
.panel-head h3 { margin: 0; }
.muted { color: var(--muted); font-size: 12px; }
.inline-message, .inline-error { padding: 10px 12px; border-radius: 8px; font-size: 14px; }
.inline-message { background: #ecfdf3; border: 1px solid #86efac; color: #027a48; }
.inline-error { background: #fef3f2; border: 1px solid #fda29b; color: #b42318; }
.row-reason { margin: 4px 0 0; max-width: 280px; font-size: 12px; color: var(--muted); }
.invalid, .conflict { color: #b42318; font-weight: 700; }
.inline-form { display: flex; flex-wrap: wrap; gap: 8px; align-items: end; margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--border); font-size: 13px; }
.inline-form label { display: flex; flex-direction: column; gap: 4px; }
.inline-form input { width: 130px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.compact { font-size: 12px; }
code { background: #f1f5f9; padding: 1px 4px; border-radius: 4px; }
</style>
