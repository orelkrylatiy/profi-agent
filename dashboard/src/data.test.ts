import { afterEach, describe, expect, it, vi } from 'vitest'

import { loadDashboardData, validateDashboardData } from './data'

const payload = {
  schema_version: 2,
  generated_at: '2026-09-14T12:00:00Z',
  source_date: '2026-09-14',
  source_generated_at: '2026-09-14T11:59:00+05:00',
  source_code_revision: 'abc123',
  timezone: 'Asia/Yekaterinburg',
  experiment_scope: 'all_time_current_db',
  accounts: [],
  history: [],
  experiments: [],
  data_quality: { warnings: [], legacy_history_skipped: 0 },
  privacy: {},
}

afterEach(() => vi.unstubAllGlobals())

describe('dashboard data contract', () => {
  it('accepts exporter schema v2', () => {
    expect(validateDashboardData(payload).schema_version).toBe(2)
  })

  it('rejects stale schema v1 instead of rendering misleading data', () => {
    expect(() => validateDashboardData({ ...payload, schema_version: 1 })).toThrow(
      /unsupported schema/,
    )
  })

  it('loads a valid v2 payload through fetch', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 })),
    )
    await expect(loadDashboardData()).resolves.toMatchObject({ schema_version: 2 })
  })
})
