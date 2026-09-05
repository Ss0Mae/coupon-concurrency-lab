// 쿠폰 발급 부하 스크립트. 모든 실험이 이 한 파일을 환경변수만 바꿔 사용한다.
//   STRATEGY   no-lock | pessimistic | optimistic | conditional
//   VUS        동시 사용자 수
//   MODE       iterations(기본: 요청 수 고정) | duration(시간 고정)
//   ITERATIONS MODE=iterations 일 때 전체 요청 수 (기본 1000)
//   DURATION   MODE=duration 일 때 지속 시간 (기본 10s)
//   USERS      사용자 풀 크기. userId = 1 + (전역 반복 index % USERS). 기본 = 무한(중복 없음)
//   COUPON_ID  기본 1
//   OUT        요약 JSON 출력 경로
import http from 'k6/http';
import exec from 'k6/execution';
import { Counter, Trend } from 'k6/metrics';

const strategy = __ENV.STRATEGY || 'conditional';
const vus = Number(__ENV.VUS || 100);
const mode = __ENV.MODE || 'iterations';
const users = Number(__ENV.USERS || 0);
const couponId = __ENV.COUPON_ID || '1';
const url = `http://127.0.0.1:8080/api/coupons/${couponId}/issue/${strategy}`;

const scenario = mode === 'duration'
  ? { executor: 'constant-vus', vus, duration: __ENV.DURATION || '10s', gracefulStop: '30s' }
  : { executor: 'shared-iterations', vus, iterations: Number(__ENV.ITERATIONS || 1000), maxDuration: '10m' };

export const options = {
  scenarios: { issue: scenario },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(50)', 'p(90)', 'p(95)', 'p(99)'],
  noConnectionReuse: false,
  discardResponseBodies: false,
};

const issued = new Counter('issued');
const soldOut = new Counter('sold_out');
const duplicate = new Counter('duplicate');
const serverError = new Counter('server_error');
const other = new Counter('other');
const issuedDur = new Trend('issued_duration', true);
const soldOutDur = new Trend('sold_out_duration', true);

export default function () {
  const idx = exec.scenario.iterationInTest; // 실행 전체에서 유일한 정수
  const userId = 1 + (users > 0 ? idx % users : idx);
  const res = http.post(url, JSON.stringify({ userId }), {
    headers: { 'Content-Type': 'application/json' },
    tags: { strategy },
  });
  const d = res.timings.duration;
  if (res.status === 200) { issued.add(1); issuedDur.add(d); }
  else if (res.status === 410) { soldOut.add(1); soldOutDur.add(d); }
  else if (res.status === 409) duplicate.add(1);
  else if (res.status >= 500) serverError.add(1);
  else other.add(1);
}

export function handleSummary(data) {
  const out = __ENV.OUT || 'k6-summary.json';
  return { [out]: JSON.stringify(data) };
}
