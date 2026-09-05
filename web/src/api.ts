export type StrategyKey = 'no-lock' | 'pessimistic' | 'optimistic' | 'conditional'

export const STRATEGIES: { key: StrategyKey; name: string; color: string; how: string }[] = [
  { key: 'no-lock', name: '락 없음', color: '#eb6834', how: '읽은 값 + 1 을 그대로 UPDATE. 동시에 읽은 요청끼리 서로 덮어씀' },
  { key: 'pessimistic', name: '비관적 락', color: '#2a78d6', how: 'SELECT … FOR UPDATE 로 행을 잠그고 커밋까지 붙잡음' },
  { key: 'optimistic', name: '낙관적 락', color: '#eda100', how: 'UPDATE … WHERE version = ? 가 0행이면 최대 20회 재시도' },
  { key: 'conditional', name: '조건부 UPDATE', color: '#1baf7a', how: 'UPDATE … WHERE issued_quantity < total_quantity 한 문장으로 검사와 증가를 원자화' },
]

export type Params = { totalQuantity: number; users: number; requests: number; concurrency: number }

export type DbState = { issued_quantity: number; total_quantity: number; issues: number; distinct_users: number }

export type RunResult = {
  strategy: string
  params: Params & { couponId: number }
  elapsed_ms: number
  tps: number
  success_tps: number
  counts: { issued: number; sold_out: number; duplicate: number; server_error: number }
  latency: { avg: number; p50: number; p95: number; p99: number; max: number }
  db: DbState
  integrity: { over_issue: number; dup_issue: number; resp_db_mismatch: number; stock_mismatch: number; ok: boolean }
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export const api = {
  state: () => json<DbState>('/api/demo/state?couponId=1'),
  run: (strategy: StrategyKey, p: Params) =>
    json<RunResult>('/api/demo/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strategy, couponId: 1, ...p }),
    }),
}

export const fmt = (n: number | null | undefined, d = 0) =>
  n == null ? '–' : n.toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d })
