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
  blocking_active: boolean
  probe_due: boolean
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
    responses_unknown: number
  }
  cohort: {
    candidates: number
    details_ready: number
    drafts_generated: number
    responses_sent: number
    responses_unknown: number
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
  schema_version: 2
  generated_at: string
  source_date: string | null
  source_generated_at: string | null
  source_code_revision: string | null
  timezone: string | null
  experiment_scope: 'all_time_current_db' | string
  accounts: Account[]
  history: HistoryRow[]
  experiments: ExperimentRow[]
  data_quality: { warnings: string[]; legacy_history_skipped: number }
  privacy: Record<string, boolean>
}
