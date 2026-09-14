import type { DashboardData } from './types'

const defaultDataUrl = '/ops/dashboard.json'

export function dashboardDataUrl(): string {
  return import.meta.env.VITE_DASHBOARD_DATA_URL || defaultDataUrl
}

export async function loadDashboardData(signal?: AbortSignal): Promise<DashboardData> {
  const response = await fetch(dashboardDataUrl(), {
    signal,
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`dashboard data: HTTP ${response.status}`)
  }
  const payload = (await response.json()) as DashboardData
  if (!payload || payload.schema_version !== 1 || !Array.isArray(payload.accounts)) {
    throw new Error('dashboard data: unsupported schema')
  }
  return payload
}
