export type CapabilityStatus =
  | 'UNKNOWN'
  | 'READY'
  | 'NO_BALANCE'
  | 'COMMISSION_UNAVAILABLE'
  | 'COMMISSION_DAILY_LIMIT'
  | 'AUTH_REQUIRED'
  | 'UI_UNKNOWN'

export type Capability = {
  status: CapabilityStatus | string
  reason: string
  checked_at: number
  blocked_until: number
  respond_mode: string
  balance_known: boolean
  price_known: boolean
}

export type AccountMetrics = {
  events: {
    feed_new_orders: number
    candidates: number
    details_ready: number
    drafts_generated: number
    sends_started: number
    responses_sent: number
  }
  cohort: {
    responses_failed: number
    responses_skipped: number
    client_replied: number
    reply_yield_pct: number | null
  }
  runtime: {
    worker_seen_today: boolean
    supervisor_seen_today: boolean
    last_seen_at: string | null
    availability_incidents: number
    events: Record<string, number>
  }
  inventory: {
    send_status: Record<string, number>
    details_errors: number
    draft_errors: number
  }
}

export type Account = {
  id: string
  label: string
  capability: Capability
  metrics: AccountMetrics
}

export type HistoryRow = {
  date: string
  feed_new_orders: number
  feed_orders_seen: number
  candidates: number
  details_ready: number
  drafts_generated: number
  sends_started: number
  responses_sent: number
  responses_unknown: number
  responses_failed: number
  responses_skipped: number
  client_replied: number
  availability_incidents: number
}

export type ExperimentRow = {
  account_id: string
  prompt_experiment: string
  prompt_variant: string
  assigned: number
  evaluated: number
  generated: number
  fallbacks: number
  sent: number
  replied: number
  send_rate_pct: number | null
  reply_rate_pct: number | null
  reply_yield_pct: number | null
  avg_reply_min: number | null
}

export type DashboardData = {
  schema_version: number
  generated_at: string
  source_date: string | null
  source_code_revision: string | null
  timezone: string | null
  totals: Record<string, unknown>
  accounts: Account[]
  history: HistoryRow[]
  experiments: ExperimentRow[]
  privacy: Record<string, boolean>
}
