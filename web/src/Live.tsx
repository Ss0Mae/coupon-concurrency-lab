import { useRef, useState, type CSSProperties } from 'react'
import { api, fmt, STRATEGIES, type DbState, type Params, type RunResult, type StrategyKey } from './api'

type Lane = { status: 'idle' | 'running' | 'done' | 'error'; result?: RunResult; live?: DbState; error?: string }
type Run = RunResult & { at: string }

const PRESETS: { name: string; p: Params }[] = [
  { name: '쿠폰 100장에 1,000명', p: { totalQuantity: 100, users: 1000, requests: 1000, concurrency: 200 } },
  { name: '1,000명이 두 번씩', p: { totalQuantity: 100, users: 1000, requests: 2000, concurrency: 200 } },
  { name: '이미 품절', p: { totalQuantity: 0, users: 1000, requests: 1000, concurrency: 200 } },
  { name: '재고 무제한', p: { totalQuantity: 10_000_000, users: 1000, requests: 2000, concurrency: 200 } },
]

const FIELDS: { k: keyof Params; label: string; max: number }[] = [
  { k: 'totalQuantity', label: '쿠폰 재고', max: 10_000_000 },
  { k: 'users', label: '사용자 수', max: 1_000_000 },
  { k: 'requests', label: '요청 수', max: 20_000 },
  { k: 'concurrency', label: '동시 요청', max: 1000 },
]

export default function Live({ appUp, onAppStatus }: { appUp: boolean | null; onAppStatus: (up: boolean) => void }) {
  const [p, setP] = useState<Params>(PRESETS[0].p)
  const [lanes, setLanes] = useState<Record<StrategyKey, Lane>>(
    () => Object.fromEntries(STRATEGIES.map((s) => [s.key, { status: 'idle' }])) as Record<StrategyKey, Lane>,
  )
  const [history, setHistory] = useState<Run[]>([])
  const running = useRef<StrategyKey | null>(null)
  const busy = running.current != null

  const setLane = (k: StrategyKey, patch: Partial<Lane>) => setLanes((ls) => ({ ...ls, [k]: { ...ls[k], ...patch } }))

  async function runOne(k: StrategyKey) {
    running.current = k
    setLane(k, { status: 'running', result: undefined, live: undefined, error: undefined })
    // 실행 중 0.25초마다 DB 상태를 읽어 띠가 차오르는 과정을 보여 준다
    const poll = window.setInterval(() => {
      api.state().then((s) => running.current === k && setLane(k, { live: s })).catch(() => {})
    }, 250)
    try {
      const r = await api.run(k, p)
      setLane(k, { status: 'done', result: r, live: r.db })
      setHistory((h) => [{ ...r, at: new Date().toLocaleTimeString('ko-KR') }, ...h])
      onAppStatus(true)
    } catch (e) {
      setLane(k, { status: 'error', error: e instanceof Error ? e.message : String(e) })
      onAppStatus(false)
    } finally {
      window.clearInterval(poll)
      running.current = null
      setLanes((ls) => ({ ...ls })) // busy 재계산
    }
  }

  async function runAll() {
    for (const s of STRATEGIES) await runOne(s.key)
  }

  const activePreset = PRESETS.find((x) => FIELDS.every((f) => x.p[f.k] === p[f.k]))?.name

  return (
    <section aria-labelledby="live-title">
      <h2 id="live-title" className="section-title">직접 실행</h2>
      <p className="section-note">
        실행하면 쿠폰을 초기화한 뒤 발급 API 를 동시에 호출하고, 끝난 뒤 DB 를 세어 응답과 대조합니다. 네 전략은 같은 조건으로 차례로 달립니다.
        동시 요청이 200 을 넘으면 Tomcat 스레드(200) 앞에서 줄을 섭니다.
      </p>

      <div className="bench-controls">
        {FIELDS.map((f) => (
          <label key={f.k} className="field">
            {f.label}
            <input
              type="number" min={0} max={f.max} value={p[f.k]} disabled={busy}
              onChange={(e) => setP({ ...p, [f.k]: Math.max(0, Math.min(f.max, Number(e.target.value) || 0)) })}
            />
          </label>
        ))}
        <div className="presets">
          {PRESETS.map((x) => (
            <button key={x.name} type="button" disabled={busy} aria-pressed={activePreset === x.name} onClick={() => setP(x.p)}>{x.name}</button>
          ))}
        </div>
        <button type="button" className="run-all" disabled={busy || appUp === false} onClick={runAll}>
          {busy ? '실행 중' : '네 전략 모두 실행'}
        </button>
      </div>

      {appUp === false && (
        <p className="alert" role="alert">
          발급 API(8080) 에 연결할 수 없습니다. 프로젝트 루트에서 <code>docker compose up -d</code> 와 <code>bench/app.sh start</code> 를 실행한 뒤 새로고침하세요.
        </p>
      )}

      <div className="lanes">
        {STRATEGIES.map((s) => (
          <LaneView key={s.key} s={s} lane={lanes[s.key]} p={p} busy={busy || appUp === false} onRun={() => runOne(s.key)} />
        ))}
      </div>

      {history.length > 0 && (
        <>
          <h3 className="subhead">실행 기록</h3>
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>시각</th><th>전략</th><th>재고</th><th>사용자</th><th>요청</th><th>동시</th>
                  <th>발급 응답</th><th>품절</th><th>중복 차단</th><th>5xx</th>
                  <th>DB 발급 행</th><th>초과 발급</th><th>중복 발급</th><th>p50</th><th>p95</th><th>p99</th><th>전체 TPS</th><th>정합</th>
                </tr>
              </thead>
              <tbody>
                {history.map((r, i) => {
                  const s = STRATEGIES.find((x) => x.key === r.strategy.toLowerCase().replace('_', '-'))!
                  return (
                    <tr key={i} className={r.integrity.ok ? '' : 'fail'}>
                      <td>{r.at}</td>
                      <td><i className="swatch" style={{ background: s.color }} />{s.name}</td>
                      <td>{fmt(r.params.totalQuantity)}</td><td>{fmt(r.params.users)}</td><td>{fmt(r.params.requests)}</td><td>{fmt(r.params.concurrency)}</td>
                      <td>{fmt(r.counts.issued)}</td><td>{fmt(r.counts.sold_out)}</td><td>{fmt(r.counts.duplicate)}</td>
                      <td className={r.counts.server_error ? 'num-bad' : ''}>{fmt(r.counts.server_error)}</td>
                      <td>{fmt(r.db.issues)}</td>
                      <td className={r.integrity.over_issue ? 'num-bad' : ''}>{fmt(r.integrity.over_issue)}</td>
                      <td className={r.integrity.dup_issue ? 'num-bad' : ''}>{fmt(r.integrity.dup_issue)}</td>
                      <td>{fmt(r.latency.p50, 1)} ms</td><td>{fmt(r.latency.p95, 1)} ms</td><td>{fmt(r.latency.p99, 1)} ms</td>
                      <td>{fmt(r.tps, 1)}</td>
                      <td>{r.integrity.ok ? '✓ 유지' : '✕ 깨짐'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}

function LaneView({ s, lane, p, busy, onRun }: { s: (typeof STRATEGIES)[number]; lane: Lane; p: Params; busy: boolean; onRun: () => void }) {
  const r = lane.result
  const db = lane.live ?? r?.db
  const total = db?.total_quantity ?? p.totalQuantity
  const issues = db?.issues ?? 0
  const counter = db?.issued_quantity ?? 0
  const requests = r?.params.requests ?? p.requests
  const scale = Math.max(Math.min(total, requests), issues, 1)
  const pct = (n: number) => `${Math.min(100, (n / scale) * 100)}%`
  const within = Math.min(issues, total)
  const over = Math.max(0, issues - total)
  const c = r?.counts
  const ig = r?.integrity

  let verdict: { cls: string; text: string }
  if (lane.status === 'error') verdict = { cls: 'fail', text: `실행 실패: ${lane.error}` }
  else if (lane.status === 'running') verdict = { cls: 'pending', text: `실행 중, 지금까지 DB 발급 행 ${fmt(issues)}건` }
  else if (!r || !ig || !c) verdict = { cls: 'pending', text: '아직 실행 전' }
  else if (ig.ok) verdict = { cls: 'ok', text: `정합 유지: 응답 ${fmt(c.issued)}건 = DB ${fmt(r.db.issues)}행 = 카운터 ${fmt(r.db.issued_quantity)}, 재고 ${fmt(r.db.total_quantity)} 안에서 끝남` }
  else {
    const parts = []
    if (ig.over_issue) parts.push(`재고보다 ${fmt(ig.over_issue)}장 더 발급`)
    if (ig.dup_issue) parts.push(`같은 사용자에게 ${fmt(ig.dup_issue)}건 중복 발급`)
    if (ig.stock_mismatch) parts.push(`카운터가 DB 행보다 ${fmt(ig.stock_mismatch)} 적음(lost update)`)
    if (ig.resp_db_mismatch) parts.push(`응답과 DB 가 ${fmt(Math.abs(ig.resp_db_mismatch))}건 어긋남`)
    verdict = { cls: 'fail', text: '정합 깨짐: ' + parts.join(', ') }
  }

  return (
    <article className="lane" style={{ '--c': s.color } as CSSProperties} aria-label={s.name}>
      <div className="lane-head">
        <h3>{s.name}</h3>
        <p className="how">{s.how}</p>
        <button type="button" disabled={busy} onClick={onRun}>{lane.status === 'running' ? '실행 중' : '이 전략만 실행'}</button>
      </div>

      <div className="track">
        <div className="strip" style={{ '--cell': scale <= 200 ? `${100 / scale}%` : '1%' } as CSSProperties} role="img"
          aria-label={db ? `재고 ${fmt(total)} 중 DB 발급 ${fmt(issues)}건, 카운터 ${fmt(counter)}` : '실행 전'}>
          {db ? (
            <>
              <div className="fill" style={{ width: pct(within) }} />
              {over > 0 && <div className="over" style={{ left: pct(within), width: pct(over) }} />}
              <div className="cells" />
              {total <= scale && <div className="bound" style={{ left: pct(total) }}><span>재고 {fmt(total)}</span></div>}
              <div className="counter" style={{ left: pct(counter) }}><span>카운터 {fmt(counter)}</span></div>
            </>
          ) : (
            <div className="empty">칸 하나가 쿠폰 한 장입니다. 실행하면 발급된 만큼 채워집니다.</div>
          )}
        </div>
        {c && (
          <>
            <div className="mix" aria-hidden="true">
              <i style={{ flex: c.issued, background: s.color }} />
              <i style={{ flex: c.sold_out, background: 'var(--soldout)' }} />
              <i style={{ flex: c.duplicate, background: 'var(--dup)' }} />
              <i style={{ flex: c.server_error, background: 'var(--bad)' }} />
            </div>
            <div className="mix-legend">
              <span><i style={{ background: s.color }} />발급 {fmt(c.issued)}</span>
              <span><i style={{ background: 'var(--soldout)' }} />품절 {fmt(c.sold_out)}</span>
              <span><i style={{ background: 'var(--dup)' }} />중복 차단 {fmt(c.duplicate)}</span>
              <span><i style={{ background: 'var(--bad)' }} />서버 오류 {fmt(c.server_error)}</span>
            </div>
          </>
        )}
      </div>

      <div className="lane-stats">
        <Stat v={c ? fmt(c.issued) : '–'} label="발급 응답" />
        <Stat v={db ? fmt(issues) : '–'} label="DB 발급 행" />
        <Stat v={db ? fmt(counter) : '–'} label="재고 카운터" />
        <Stat v={ig ? fmt(ig.over_issue) : '–'} label="초과 발급" bad={!!ig?.over_issue} />
        <Stat v={ig ? fmt(ig.dup_issue) : '–'} label="중복 발급" bad={!!ig?.dup_issue} />
        <Stat v={c ? fmt(c.server_error) : '–'} label="서버 오류" bad={!!c?.server_error} />
        <Stat v={r ? fmt(r.latency.p95) : '–'} label="p95 ms" />
        <Stat v={r ? fmt(r.tps) : '–'} label={r ? `TPS, ${fmt(r.elapsed_ms / 1000, 2)}초` : 'TPS'} />
        <p className={'verdict ' + verdict.cls}>{verdict.text}</p>
      </div>
    </article>
  )
}

function Stat({ v, label, bad }: { v: string; label: string; bad?: boolean }) {
  return (
    <div className={'stat' + (bad ? ' bad' : '')}>
      <b>{v}</b>
      <small>{label}</small>
    </div>
  )
}
