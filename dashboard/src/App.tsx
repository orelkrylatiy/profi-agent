import { AreaChart, BarChart } from '@mantine/charts'
import {
  Alert,
  Badge,
  Button,
  Card,
  Container,
  Divider,
  Group,
  Loader,
  Paper,
  Progress,
  ScrollArea,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  ThemeIcon,
  Title,
} from '@mantine/core'
import { useEffect, useMemo, useState } from 'react'

import { dashboardDataUrl, loadDashboardData } from './data'
import type { Account, DashboardData, ExperimentRow, HistoryRow } from './types'

const compactNumber = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const integerNumber = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

function sum(values: number[]): number {
  return values.reduce((total, value) => total + value, 0)
}

function pct(value: number | null): string {
  return value === null ? '—' : `${compactNumber.format(value)}%`
}

function formatTimestamp(value: number): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value * 1000))
}

function capabilityColor(status: string): string {
  const map: Record<string, string> = {
    READY: 'teal',
    UNKNOWN: 'gray',
    NO_BALANCE: 'orange',
    COMMISSION_UNAVAILABLE: 'yellow',
    COMMISSION_DAILY_LIMIT: 'violet',
    AUTH_REQUIRED: 'red',
    UI_UNKNOWN: 'red',
  }
  return map[status] || 'gray'
}

function capabilityLabel(status: string): string {
  const map: Record<string, string> = {
    READY: 'Готов к откликам',
    UNKNOWN: 'Не проверен',
    NO_BALANCE: 'Не хватает баланса',
    COMMISSION_UNAVAILABLE: 'Комиссия недоступна',
    COMMISSION_DAILY_LIMIT: 'Лимит комиссии',
    AUTH_REQUIRED: 'Нужен логин',
    UI_UNKNOWN: 'Неизвестный UI',
  }
  return map[status] || status
}

function KpiCard({
  label,
  value,
  hint,
}: {
  label: string
  value: number | string
  hint: string
}) {
  return (
    <Card className="metric-card" radius="lg" padding="lg" withBorder>
      <Stack gap={6}>
        <Text size="xs" tt="uppercase" fw={700} c="dimmed" className="metric-label">
          {label}
        </Text>
        <Text className="metric-value" fw={750}>
          {typeof value === 'number' ? integerNumber.format(value) : value}
        </Text>
        <Text size="xs" c="dimmed">
          {hint}
        </Text>
      </Stack>
    </Card>
  )
}

function AccountCard({ account }: { account: Account }) {
  const { capability, metrics } = account
  const feedHealthy = metrics.runtime.worker_seen_today
  const sends = metrics.events.responses_sent
  const candidates = metrics.events.candidates
  const conversion = candidates ? (sends / candidates) * 100 : 0

  return (
    <Card radius="lg" padding="lg" withBorder className="account-card">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <div>
            <Text fw={700}>{account.label}</Text>
            <Text size="xs" c="dimmed">
              {capability.respond_mode === 'commission'
                ? 'Комиссия'
                : capability.respond_mode === 'pay'
                  ? 'Платный отклик'
                  : 'Режим не определён'}
            </Text>
          </div>
          <Badge color={capabilityColor(capability.status)} variant="light" size="lg">
            {capabilityLabel(capability.status)}
          </Badge>
        </Group>

        <Paper className="capability-box" radius="md" p="sm" withBorder>
          <Group gap="xs" mb={4}>
            <ThemeIcon
              size={18}
              radius="xl"
              color={feedHealthy ? 'teal' : 'gray'}
              variant="light"
            >
              <span className="status-dot">•</span>
            </ThemeIcon>
            <Text size="sm" fw={600}>
              Worker {feedHealthy ? 'виден сегодня' : 'не виден сегодня'}
            </Text>
          </Group>
          <Text size="xs" c="dimmed" lineClamp={2}>
            {capability.reason}
          </Text>
          {capability.blocked_until > 0 && (
            <Text size="xs" mt={6} c="dimmed">
              Повторная проверка: {formatTimestamp(capability.blocked_until)}
            </Text>
          )}
        </Paper>

        <SimpleGrid cols={3} spacing="xs">
          <div>
            <Text size="xs" c="dimmed">
              Кандидаты
            </Text>
            <Text fw={700}>{candidates}</Text>
          </div>
          <div>
            <Text size="xs" c="dimmed">
              Отправлено
            </Text>
            <Text fw={700}>{sends}</Text>
          </div>
          <div>
            <Text size="xs" c="dimmed">
              Инциденты
            </Text>
            <Text fw={700}>{metrics.runtime.availability_incidents}</Text>
          </div>
        </SimpleGrid>

        <div>
          <Group justify="space-between" mb={5}>
            <Text size="xs" c="dimmed">
              candidate → sent
            </Text>
            <Text size="xs" fw={600}>
              {compactNumber.format(conversion)}%
            </Text>
          </Group>
          <Progress value={Math.min(100, conversion)} size="sm" radius="xl" />
        </div>
      </Stack>
    </Card>
  )
}

function Overview({ data }: { data: DashboardData }) {
  const current = useMemo(() => {
    const accounts = data.accounts
    return {
      feed: sum(accounts.map((account) => account.metrics.events.feed_new_orders)),
      candidates: sum(accounts.map((account) => account.metrics.events.candidates)),
      details: sum(accounts.map((account) => account.metrics.events.details_ready)),
      drafts: sum(accounts.map((account) => account.metrics.events.drafts_generated)),
      sends: sum(accounts.map((account) => account.metrics.events.responses_sent)),
      replies: sum(accounts.map((account) => account.metrics.cohort.client_replied)),
      incidents: sum(accounts.map((account) => account.metrics.runtime.availability_incidents)),
    }
  }, [data.accounts])

  const funnelData = [
    { stage: 'Новые', value: current.feed },
    { stage: 'Кандидаты', value: current.candidates },
    { stage: 'Детали', value: current.details },
    { stage: 'Драфты', value: current.drafts },
    { stage: 'Отправки', value: current.sends },
    { stage: 'Ответы', value: current.replies },
  ]

  return (
    <Stack gap="lg">
      <SimpleGrid cols={{ base: 2, md: 5 }} spacing="md">
        <KpiCard label="Новые заказы" value={current.feed} hint="увидели в фиде" />
        <KpiCard label="Кандидаты" value={current.candidates} hint="прошли hard filter" />
        <KpiCard label="Отклики" value={current.sends} hint="подтверждённо sent" />
        <KpiCard label="Ответы" value={current.replies} hint="клиент ответил" />
        <KpiCard label="Инциденты" value={current.incidents} hint="availability clusters" />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
        <Card radius="lg" padding="lg" withBorder>
          <Group justify="space-between" mb="md">
            <div>
              <Text fw={700}>Динамика за период</Text>
              <Text size="xs" c="dimmed">
                Фид, кандидаты и подтверждённые отправки
              </Text>
            </div>
            <Badge variant="light">{data.history.length} дней</Badge>
          </Group>
          {data.history.length > 0 ? (
            <AreaChart
              h={300}
              data={data.history}
              dataKey="date"
              withLegend
              curveType="monotone"
              series={[
                { name: 'feed_new_orders', label: 'Новые', color: 'gray.5' },
                { name: 'candidates', label: 'Кандидаты', color: 'indigo.6' },
                { name: 'responses_sent', label: 'Отклики', color: 'teal.6' },
              ]}
            />
          ) : (
            <EmptyChart text="История появится после публикации ежедневных snapshots" />
          )}
        </Card>

        <Card radius="lg" padding="lg" withBorder>
          <Text fw={700}>Воронка сегодня</Text>
          <Text size="xs" c="dimmed" mb="md">
            Где именно теряются подходящие заказы
          </Text>
          <BarChart
            h={300}
            data={funnelData}
            dataKey="stage"
            series={[{ name: 'value', label: 'Количество', color: 'indigo.6' }]}
            tickLine="none"
            gridAxis="none"
          />
        </Card>
      </SimpleGrid>

      <div>
        <Group justify="space-between" mb="sm">
          <div>
            <Title order={3}>Аккаунты</Title>
            <Text size="sm" c="dimmed">
              Capability показывает не «жив ли worker», а может ли аккаунт сейчас откликаться.
            </Text>
          </div>
        </Group>
        {data.accounts.length > 0 ? (
          <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }} spacing="lg">
            {data.accounts.map((account) => (
              <AccountCard account={account} key={account.id} />
            ))}
          </SimpleGrid>
        ) : (
          <Alert color="gray" title="Нет аккаунтов в dashboard dataset">
            Collector публикует только явно настроенные аккаунты и не угадывает их по случайным
            SQLite-файлам.
          </Alert>
        )}
      </div>
    </Stack>
  )
}

function experimentChartRows(rows: ExperimentRow[]) {
  return rows.map((row) => ({
    variant: `${row.account_id} · ${row.prompt_variant}`,
    send_rate: row.send_rate_pct || 0,
    reply_rate: row.reply_rate_pct || 0,
    reply_yield: row.reply_yield_pct || 0,
  }))
}

function Experiments({ rows }: { rows: ExperimentRow[] }) {
  const experiments = useMemo(() => {
    const names = new Set(rows.map((row) => row.prompt_experiment))
    return Array.from(names)
  }, [rows])

  if (rows.length === 0) {
    return (
      <Alert title="A/B/C данные ещё не накоплены" color="gray">
        После первых LLM-evaluated кандидатов здесь появятся варианты, send rate, reply rate и
        основной acquisition yield.
      </Alert>
    )
  }

  return (
    <Stack gap="xl">
      {experiments.map((experiment) => {
        const experimentRows = rows.filter((row) => row.prompt_experiment === experiment)
        const chartRows = experimentChartRows(experimentRows)
        return (
          <Stack gap="md" key={experiment}>
            <Group justify="space-between">
              <div>
                <Title order={3}>{experiment}</Title>
                <Text size="sm" c="dimmed">
                  Основная метрика: replies / LLM-evaluated candidates (yield)
                </Text>
              </div>
              <Badge variant="outline">
                {sum(experimentRows.map((row) => row.evaluated))} evaluated
              </Badge>
            </Group>

            <Card radius="lg" padding="lg" withBorder>
              <BarChart
                h={320}
                data={chartRows}
                dataKey="variant"
                withLegend
                yAxisProps={{ domain: [0, 100] }}
                valueFormatter={(value) => `${value}%`}
                series={[
                  { name: 'reply_yield', label: 'Yield', color: 'teal.6' },
                  { name: 'send_rate', label: 'Send rate', color: 'indigo.6' },
                  { name: 'reply_rate', label: 'Reply rate', color: 'grape.6' },
                ]}
              />
            </Card>

            <Card radius="lg" padding={0} withBorder>
              <ScrollArea>
                <Table
                  striped
                  highlightOnHover
                  horizontalSpacing="lg"
                  verticalSpacing="sm"
                  miw={900}
                >
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Аккаунт</Table.Th>
                      <Table.Th>Вариант</Table.Th>
                      <Table.Th>Assigned</Table.Th>
                      <Table.Th>Evaluated</Table.Th>
                      <Table.Th>Fallback</Table.Th>
                      <Table.Th>Sent</Table.Th>
                      <Table.Th>Replies</Table.Th>
                      <Table.Th>Send %</Table.Th>
                      <Table.Th>Reply %</Table.Th>
                      <Table.Th>Yield %</Table.Th>
                      <Table.Th>Сред. ответ</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {experimentRows.map((row) => (
                      <Table.Tr key={`${row.account_id}-${row.prompt_variant}`}>
                        <Table.Td>{row.account_id}</Table.Td>
                        <Table.Td>
                          <Badge variant="light">{row.prompt_variant}</Badge>
                        </Table.Td>
                        <Table.Td>{row.assigned}</Table.Td>
                        <Table.Td>
                          <Group gap="xs" wrap="nowrap">
                            <Text size="sm">{row.evaluated}</Text>
                            {row.evaluated < 30 && (
                              <Badge size="xs" color="yellow" variant="light">
                                мало данных
                              </Badge>
                            )}
                          </Group>
                        </Table.Td>
                        <Table.Td>{row.fallbacks}</Table.Td>
                        <Table.Td>{row.sent}</Table.Td>
                        <Table.Td>{row.replied}</Table.Td>
                        <Table.Td>{pct(row.send_rate_pct)}</Table.Td>
                        <Table.Td>{pct(row.reply_rate_pct)}</Table.Td>
                        <Table.Td>
                          <Text fw={700}>{pct(row.reply_yield_pct)}</Text>
                        </Table.Td>
                        <Table.Td>
                          {row.avg_reply_min === null ? '—' : `${row.avg_reply_min} мин`}
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </ScrollArea>
            </Card>
          </Stack>
        )
      })}
    </Stack>
  )
}

function Reliability({ accounts, history }: { accounts: Account[]; history: HistoryRow[] }) {
  const incidentData = history.map((row) => ({
    date: row.date,
    incidents: row.availability_incidents,
    failed: row.responses_failed,
  }))

  const eventRows = accounts
    .flatMap((account) =>
      Object.entries(account.metrics.runtime.events).map(([event, count]) => ({
        account: account.label,
        event,
        count,
      })),
    )
    .sort((a, b) => b.count - a.count)

  return (
    <Stack gap="lg">
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
        <Card radius="lg" padding="lg" withBorder>
          <Text fw={700}>Availability и failed</Text>
          <Text size="xs" c="dimmed" mb="md">
            Важно различать независимые инциденты и outcomes кандидатов
          </Text>
          {incidentData.length ? (
            <AreaChart
              h={300}
              data={incidentData}
              dataKey="date"
              withLegend
              series={[
                { name: 'incidents', label: 'Availability incidents', color: 'orange.6' },
                { name: 'failed', label: 'Failed candidates', color: 'red.6' },
              ]}
            />
          ) : (
            <EmptyChart text="Нет исторических данных" />
          )}
        </Card>

        <Card radius="lg" padding="lg" withBorder>
          <Text fw={700}>Технические события сегодня</Text>
          <Text size="xs" c="dimmed" mb="md">
            Сортировка по количеству в canonical logs
          </Text>
          {eventRows.length ? (
            <Stack gap="xs">
              {eventRows.slice(0, 10).map((row) => (
                <Group key={`${row.account}-${row.event}`} justify="space-between">
                  <div>
                    <Text size="sm" fw={600}>
                      {row.event}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {row.account}
                    </Text>
                  </div>
                  <Badge variant="light" color={row.count > 10 ? 'red' : 'gray'}>
                    {row.count}
                  </Badge>
                </Group>
              ))}
            </Stack>
          ) : (
            <Text size="sm" c="dimmed">
              Событий нет.
            </Text>
          )}
        </Card>
      </SimpleGrid>

      <Card radius="lg" padding={0} withBorder>
        <ScrollArea>
          <Table horizontalSpacing="lg" verticalSpacing="md" miw={820} highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Аккаунт</Table.Th>
                <Table.Th>Capability</Table.Th>
                <Table.Th>Worker</Table.Th>
                <Table.Th>Последняя активность</Table.Th>
                <Table.Th>Инциденты</Table.Th>
                <Table.Th>Details errors</Table.Th>
                <Table.Th>Draft errors</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {accounts.map((account) => (
                <Table.Tr key={account.id}>
                  <Table.Td fw={600}>{account.label}</Table.Td>
                  <Table.Td>
                    <Badge color={capabilityColor(account.capability.status)} variant="light">
                      {capabilityLabel(account.capability.status)}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    {account.metrics.runtime.worker_seen_today ? 'виден' : 'не виден'}
                  </Table.Td>
                  <Table.Td>{account.metrics.runtime.last_seen_at || '—'}</Table.Td>
                  <Table.Td>{account.metrics.runtime.availability_incidents}</Table.Td>
                  <Table.Td>{account.metrics.inventory.details_errors}</Table.Td>
                  <Table.Td>{account.metrics.inventory.draft_errors}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Card>
    </Stack>
  )
}

function EmptyChart({ text }: { text: string }) {
  return (
    <div className="empty-chart">
      <Text size="sm" c="dimmed">
        {text}
      </Text>
    </div>
  )
}

function Dashboard({
  data,
  onRefresh,
  refreshing,
}: {
  data: DashboardData
  onRefresh: () => void
  refreshing: boolean
}) {
  return (
    <Container size="xl" py={{ base: 'md', md: 'xl' }}>
      <Stack gap="xl">
        <Group justify="space-between" align="flex-start">
          <div>
            <Group gap="xs" mb={6}>
              <Badge variant="light" color="indigo">
                Profi Agent
              </Badge>
              <Badge variant="dot" color="teal">
                privacy-safe
              </Badge>
            </Group>
            <Title order={1} className="page-title">
              Analytics & Experiments
            </Title>
            <Text c="dimmed" size="sm" mt={4}>
              {data.source_date ? `Срез за ${data.source_date}` : 'Дата среза неизвестна'}
              {data.source_code_revision ? ` · ${data.source_code_revision}` : ''}
            </Text>
          </div>
          <Button variant="light" onClick={onRefresh} loading={refreshing}>
            Обновить
          </Button>
        </Group>

        <Divider />

        <Tabs defaultValue="overview" variant="pills" keepMounted={false}>
          <Tabs.List mb="xl">
            <Tabs.Tab value="overview">Обзор</Tabs.Tab>
            <Tabs.Tab value="experiments">A/B тесты</Tabs.Tab>
            <Tabs.Tab value="reliability">Надёжность</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="overview">
            <Overview data={data} />
          </Tabs.Panel>
          <Tabs.Panel value="experiments">
            <Experiments rows={data.experiments} />
          </Tabs.Panel>
          <Tabs.Panel value="reliability">
            <Reliability accounts={data.accounts} history={data.history} />
          </Tabs.Panel>
        </Tabs>

        <Text size="xs" c="dimmed" ta="center" pb="md">
          Публичный dataset не содержит логины, имена клиентов, тексты сообщений, raw logs,
          order IDs или точные балансы.
        </Text>
      </Stack>
    </Container>
  )
}

export default function App() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    loadDashboardData(controller.signal)
      .then(setData)
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return
        setError(caught instanceof Error ? caught.message : 'Не удалось загрузить данные')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [refreshKey])

  if (loading && !data) {
    return (
      <div className="center-state">
        <Loader />
        <Text c="dimmed">Загружаю аналитический срез…</Text>
      </div>
    )
  }

  if (error && !data) {
    return (
      <Container size="sm" py={80}>
        <Alert color="orange" title="Dashboard dataset пока недоступен">
          <Stack gap="sm">
            <Text size="sm">{error}</Text>
            <Text size="sm" c="dimmed">
              Ожидаемый источник: {dashboardDataUrl()}. После первого запуска daily_publish
              появится ops/dashboard.json.
            </Text>
            <Group>
              <Button onClick={() => setRefreshKey((key) => key + 1)}>Повторить</Button>
            </Group>
          </Stack>
        </Alert>
      </Container>
    )
  }

  if (!data) return null

  return (
    <>
      {error && (
        <Alert color="orange" title="Не удалось обновить данные" radius={0}>
          Показываю последний успешно загруженный срез: {error}
        </Alert>
      )}
      <Dashboard
        data={data}
        refreshing={loading}
        onRefresh={() => setRefreshKey((key) => key + 1)}
      />
    </>
  )
}
