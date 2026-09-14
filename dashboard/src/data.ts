import type { DashboardData } from './types'

const expectedSchemaVersion = 2

export function dashboardDataUrl(): string {
  const explicit = import.meta.env.VITE_DASHBOARD_DATA_URL
  if (explicit) return explicit
  return `${import.meta.env.BASE_URL}ops/dashboard.json`
}

export function validateDashboardData(payload: unknown): DashboardData {
  if (!payload || typeof payload !== 'object') {
    throw new Error('dashboard data: payload is not an object')
  }
  const data = payload as Partial<DashboardData>
  if (data.schema_version !== expectedSchemaVersion) {
    throw new Error(`dashboard data: unsupported schema ${String(data.schema_version)}`)
  }
  if (!Array.isArray(data.accounts) || !Array.isArray(data.history) || !Array.isArray(data.experiments)) {
    throw new Error('dashboard data: malformed collections')
  }
  return data as DashboardData
}

export async function loadDashboardData(signal?: AbortSignal): Promise<DashboardData> {
  const response = await fetch(dashboardDataUrl(), { signal, cache: 'no-store' })
  if (!response.ok) {
    throw new Error(`dashboard data: HTTP ${response.status}`)
  }
  return validateDashboardData(await response.json())
}
