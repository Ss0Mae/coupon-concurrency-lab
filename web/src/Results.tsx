import { useState } from 'react'
import raw from '../../results/summary.json'
import { fmt, STRATEGIES, type StrategyKey } from './api'

type Perf = Record<string, number | null>
type Summary = {
  coherence: Record<string, Record<string, { ok: boolean; issued: number; db_issues: number; issued_qty: number; over_issue_max: number; dup_issue_max: number }>>
  perf: Record<string, Record<string, Record<string, Perf>>>
  improve: Record<string, Record<string, string[]>>
}
const S = raw as unknown as Summary

const EXP_LABEL: Record<string, string> = { coherence: '쿠폰 100장, 요청 1,000건', sustained: '재고 무제한, 10초 지속' }
const perfTabs = Object.entries(S.perf).flatMap(([exp, byVus]) => Object.keys(byVus).map((vus) => ({ exp, vus })))
  .sort((a, b) => (a.exp === b.exp ? Number(b.vus) - Number(a.vus) : a.exp === 'coherence' ? -1 : 1))
const improveTabs = Object.keys(S.improve).map((key) => {
  const [pair, cond] = key.split('@')
  const [before, after] = pair.split('->') as StrategyKey[]
  const exp = cond.replace(/v\d+$/, '')
  const vus = Number(cond.match(/v(\d+)$/)![1])
  return { key, before, after, exp, vus }
})
const name = (k: StrategyKey) => STRATEGIES.find((s) => s.key === k)!.name
const charts = import.meta.glob('../../docs/charts/*.{png,jpg}', { eager: true, query: '?url', import: 'default' }) as Record<string, string>
const CAPTIONS: Record<string, string> = {
  integrity_coherence_v1000: '정합성: 초과 발급과 중복 발급 (쿠폰 100장, 1,000 VU)',
  tps_by_strategy_coherence_v1000: '전략별 전체 TPS (쿠폰 100장, 요청 1,000건, 1,000 VU)',
  latency_p95_p99_coherence_v1000: 'p95 와 p99 응답시간 (쿠폰 100장, 1,000 VU)',
  response_mix_coherence_v1000: '응답 구성 (쿠폰 100장, 1,000 VU)',
  tps_vs_vus_coherence: '동시 사용자 수에 따른 TPS (쿠폰 100장)',
  p95_vs_vus_coherence: '동시 사용자 수에 따른 p95 (쿠폰 100장)',
  tps_by_strategy_sustained_v1000: '전략별 전체 TPS (재고 무제한, 10초, 1,000 VU)',
  tps_by_strategy_sustained_v200: '전략별 전체 TPS (재고 무제한, 10초, 200 VU)',
  latency_p95_p99_sustained_v1000: 'p95 와 p99 응답시간 (재고 무제한, 1,000 VU)',
  latency_p95_p99_sustained_v200: 'p95 와 p99 응답시간 (재고 무제한, 200 VU)',
  response_mix_sustained_v1000: '응답 구성 (재고 무제한, 1,000 VU)',
  tps_vs_vus_sustained: '동시 사용자 수에 따른 TPS (재고 무제한)',
  p95_vs_vus_sustained: '동시 사용자 수에 따른 p95 (재고 무제한)',
  hikari_acquire_vs_vus_sustained: '동시 사용자 수에 따른 커넥션 획득 대기 (재고 무제한)',
  rowlock_vs_vus_sustained: '동시 사용자 수에 따른 행 잠금 대기 (재고 무제한)',
  retries_vs_vus_sustained: '동시 사용자 수에 따른 낙관적 락 재시도 (재고 무제한)',
  poolsize_tps: 'HikariCP 풀 크기에 따른 처리량 (재고 무제한, 200 VU)',
  db_connections_timeseries_v200: '커넥션 활성, 유휴, 대기 시계열 (200 VU)',
  db_connections_timeseries_v1000: '커넥션 활성, 유휴, 대기 시계열 (1,000 VU)',
  rowlock_timeseries_v200: '행 잠금 대기 시계열 (200 VU)',
  rowlock_timeseries_v1000: '행 잠금 대기 시계열 (1,000 VU)',
  'grafana-dashboard-1': 'Grafana 대시보드, 실험 중 화면 1',
  'grafana-dashboard-2': 'Grafana 대시보드, 실험 중 화면 2',
}
const figures = Object.keys(CAPTIONS)
  .map((base) => ({ base, url: Object.entries(charts).find(([path]) => path.includes(`/${base}.`))?.[1] }))
  .filter((f): f is { base: string; url: string } => !!f.url)

export default function Results() {
  const [vus, setVus] = useState('1000')
  const [perf, setPerf] = useState(perfTabs[0])
  const [imp, setImp] = useState(improveTabs[0])
  const P = S.perf[perf.exp][perf.vus]
  const base = S.perf.coherence?.['1000']
  const before = base?.pessimistic, after = base?.conditional

  return (
    <section aria-labelledby="results-title">
      <h2 id="results-title" className="section-title">실측 결과</h2>
      <p className="section-note">
        k6 로 조건마다 워밍업 후 5회 반복한 중앙값입니다. 위의 직접 실행과 달리 측정용 스크립트와 Prometheus 지표를 함께 기록했습니다.
        반복별 값, 편차, 전체 표는 docs/results.md 에, 방법과 실패한 시도는 README 와 docs/experiments 에 있습니다.
      </p>

      {before && after && (
        <p className="resume">
          동시 요청 1,000건에서 비관적 락을 조건부 UPDATE 로 바꿔 p95 응답시간을 {fmt(before.p95)}ms 에서 {fmt(after.p95)}ms 로 단축하고,
          처리량을 {fmt(before.tps)} TPS 에서 {fmt(after.tps)} TPS 로 개선했습니다. 초과 발급과 중복 발급은 두 구현 모두 0건입니다.
        </p>
      )}

      <h3 className="subhead">정합성</h3>
      <p>쿠폰 100장, 서로 다른 사용자 1,000명, 요청 1,000건. 5회 모두 초과 발급 0, 중복 발급 0, 응답과 DB 일치, 재고와 발급 일치일 때만 유지로 봅니다.</p>
      <div className="tabs" role="tablist" aria-label="동시 사용자 수">
        {Object.keys(S.coherence).sort((a, b) => Number(b) - Number(a)).map((v) => (
          <button key={v} type="button" role="tab" aria-pressed={vus === v} onClick={() => setVus(v)}>동시 {fmt(Number(v))}명</button>
        ))}
      </div>
      <div className="tablewrap">
        <table>
          <thead><tr><th>구현</th><th>발급 응답</th><th>DB 발급 행</th><th>재고 카운터</th><th>초과 발급(최대)</th><th>중복 발급(최대)</th><th>정합</th></tr></thead>
          <tbody>
            {STRATEGIES.map((s) => {
              const r = S.coherence[vus]?.[s.key]
              if (!r) return null
              return (
                <tr key={s.key} className={r.ok ? '' : 'fail'}>
                  <td><i className="swatch" style={{ background: s.color }} />{s.name}</td>
                  <td>{fmt(r.issued)}</td><td>{fmt(r.db_issues)}</td><td>{fmt(r.issued_qty)}</td>
                  <td className={r.over_issue_max ? 'num-bad' : ''}>{fmt(r.over_issue_max)}</td>
                  <td className={r.dup_issue_max ? 'num-bad' : ''}>{fmt(r.dup_issue_max)}</td>
                  <td>{r.ok ? '✓ 유지' : '✕ 깨짐'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <h3 className="subhead">성능</h3>
      <p>전체 TPS 는 전체 응답 수를 테스트 시간으로 나눈 값, 성공 TPS 는 성공 발급 수를 테스트 시간으로 나눈 값입니다. 락 없음의 성공 발급은 초과 발급을 포함한 잘못된 성공입니다.</p>
      <div className="tabs" role="tablist" aria-label="측정 조건">
        {perfTabs.map((t) => (
          <button key={t.exp + t.vus} type="button" role="tab" aria-pressed={perf === t} onClick={() => setPerf(t)}>
            {EXP_LABEL[t.exp]}, 동시 {fmt(Number(t.vus))}명
          </button>
        ))}
      </div>
      <div className="tablewrap">
        <table>
          <thead>
            <tr>
              <th>구현</th><th>전체 요청</th><th>성공 발급</th><th>품절</th><th>중복 차단</th><th>5xx</th><th>오류율</th>
              <th>전체 TPS</th><th>성공 TPS</th><th>평균</th><th>p50</th><th>p95</th><th>p99</th><th>최대</th>
              <th>커넥션 획득 평균</th><th>대기 max</th><th>행 잠금 대기</th><th>잠금 대기 평균</th><th>충돌</th><th>재시도</th><th>MySQL CPU</th>
            </tr>
          </thead>
          <tbody>
            {STRATEGIES.map((s) => {
              const r = P?.[s.key]
              if (!r) return null
              return (
                <tr key={s.key}>
                  <td><i className="swatch" style={{ background: s.color }} />{s.name}</td>
                  <td>{fmt(r.total)}</td><td>{fmt(r.issued)}</td><td>{fmt(r.sold_out)}</td><td>{fmt(r.duplicate)}</td>
                  <td className={r.server_error ? 'num-bad' : ''}>{fmt(r.server_error)}</td>
                  <td className={r.error_rate ? 'num-bad' : ''}>{fmt(r.error_rate, 2)}%</td>
                  <td>{fmt(r.tps, 1)}</td><td>{fmt(r.success_tps, 1)}</td>
                  <td>{fmt(r.avg, 1)} ms</td><td>{fmt(r.p50, 1)} ms</td><td>{fmt(r.p95, 1)} ms</td><td>{fmt(r.p99, 1)} ms</td><td>{fmt(r.max, 1)} ms</td>
                  <td>{fmt(r.acquire_avg_ms, 2)} ms</td><td>{fmt(r.pending_max)}</td>
                  <td>{fmt(r.row_lock_waits)}</td><td>{fmt(r.row_lock_time_avg_ms, 2)} ms</td>
                  <td>{fmt(r.conflicts)}</td><td>{fmt(r.retries)}</td><td>{fmt(r.mysql_cpu_pct, 1)}%</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <h3 className="subhead">개선율</h3>
      <p>같은 조건에서 구현만 바꿔 다시 잰 값입니다. 응답시간은 낮을수록, TPS 는 높을수록 좋습니다.</p>
      <div className="tabs" role="tablist" aria-label="비교 쌍">
        {improveTabs.map((t) => (
          <button key={t.key} type="button" role="tab" aria-pressed={imp === t} onClick={() => setImp(t)}>
            {name(t.before)}에서 {name(t.after)}로, {EXP_LABEL[t.exp]}, 동시 {fmt(t.vus)}명
          </button>
        ))}
      </div>
      <div className="tablewrap">
        <table>
          <thead><tr><th>지표</th><th>변경 전 ({name(imp.before)})</th><th>변경 후 ({name(imp.after)})</th><th>변화</th></tr></thead>
          <tbody>
            {Object.entries(S.improve[imp.key]).map(([k, [b, a, ch]]) => (
              <tr key={k}><td>{k}</td><td>{b}</td><td>{a}</td><td>{ch}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="subhead">그래프</h3>
      <p>bench/report.py 가 runs.jsonl 과 Prometheus 에서 생성한 그림입니다.</p>
      <div className="figures">
        {figures.map((f) => (
          <figure key={f.base}>
            <a href={f.url} target="_blank" rel="noreferrer"><img src={f.url} alt={CAPTIONS[f.base]} loading="lazy" /></a>
            <figcaption>{CAPTIONS[f.base]}</figcaption>
          </figure>
        ))}
      </div>
    </section>
  )
}
