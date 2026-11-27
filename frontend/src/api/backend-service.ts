import { fetchJson, request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

export type CalibrationScenario = {
  ok: boolean
  [key: string]: unknown
}

async function postJson<T>(path: string, body: Record<string, unknown> = {}): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  const payload = await response.json() as T & { detail?: string; message?: string }
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || `请求失败（${response.status}）`)
  }
  return payload
}

export function getCalibrationScenario(): Promise<CalibrationScenario> {
  return fetchJson<CalibrationScenario>('/api/calibration/scenario')
}

export function resetCalibrationScenario(): Promise<CalibrationScenario> {
  return postJson<CalibrationScenario>('/api/calibration/scenario/reset')
}

export function confirmOriginalReading(): Promise<Record<string, unknown>> {
  return postJson('/api/calibration/original-reading/confirm')
}

export function saveCalibrationRule(threshold: number, operator = '>'): Promise<Record<string, unknown>> {
  return postJson('/api/calibration/rule', { threshold, operator })
}

export function processVerificationBatch(batchId = 'CAL-BATCH-001'): Promise<Record<string, unknown>> {
  return postJson('/api/calibration/verification/process', { batch_id: batchId })
}

export function processVerificationRows(rows: Record<string, string>[]): Promise<Record<string, unknown>> {
  return postJson('/api/calibration/verification/process', { rows })
}

export function submitVerificationRow(rowId: string): Promise<Record<string, unknown>> {
  return postJson(`/api/calibration/verification/${encodeURIComponent(rowId)}/submit`)
}

export function getCalibrationApproval(approvalId: string): Promise<Record<string, unknown>> {
  return fetchJson<Record<string, unknown>>(`/api/calibration/approvals/${encodeURIComponent(approvalId)}`)
}

export function approveAndActivateApproval(approvalId: string): Promise<Record<string, unknown>> {
  return postJson(`/api/calibration/approvals/${encodeURIComponent(approvalId)}/approve-and-activate`)
}

export function resolveApprovalConflict(approvalId: string): Promise<Record<string, unknown>> {
  return postJson(`/api/calibration/approvals/${encodeURIComponent(approvalId)}/resolve-conflict`)
}
