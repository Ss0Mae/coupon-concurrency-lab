"""results/*/runs.jsonl → docs/results.md (표) + docs/charts/*.png (그래프) + results/summary.json
사용: .venv/bin/python bench/report.py
"""
import json, glob, statistics, os, urllib.request, urllib.parse, datetime
import matplotlib, warnings, logging
matplotlib.use("Agg")
warnings.filterwarnings("ignore"); logging.getLogger("matplotlib").setLevel(logging.ERROR)
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
os.makedirs("docs/charts", exist_ok=True)

STRATS = ["no-lock", "pessimistic", "optimistic", "conditional"]
LABEL = {"no-lock": "락 없음", "pessimistic": "비관적 락", "optimistic": "낙관적 락", "conditional": "조건부 UPDATE"}
COLOR = {"no-lock": "#eb6834", "pessimistic": "#2a78d6", "optimistic": "#eda100", "conditional": "#1baf7a"}
plt.rcParams.update({"font.family": "Apple SD Gothic Neo", "axes.unicode_minus": False, "figure.dpi": 130,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": "#e6e6e3",
                     "axes.edgecolor": "#c9c9c4", "font.size": 9})

# ---------- load ----------
runs = []
for f in glob.glob("results/*/runs.jsonl"):
    for line in open(f):
        line = line.strip()
        if line:
            runs.append(json.loads(line))
runs = [r for r in runs if r["rep"] != "warmup"]

def get(r, path):
    v = r
    for k in path.split("."):
        v = v.get(k) if isinstance(v, dict) else None
        if v is None: return None
    return v

def group(exp, tag=""):
    g = {}
    for r in runs:
        if r["exp"] == exp and r.get("tag", "") == tag:
            g.setdefault((r["strategy"], r["vus"]), []).append(r)
    return g

def stats(rs, path):
    vals = [get(r, path) for r in rs]
    vals = [v for v in vals if v is not None]
    if not vals: return None
    return {"values": vals, "median": statistics.median(vals), "min": min(vals), "max": max(vals),
            "mean": statistics.fmean(vals), "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0, "n": len(vals)}

def med(rs, path, default=None):
    s = stats(rs, path)
    return s["median"] if s else default

def fmt(v, d=1):
    if v is None: return "-"
    if isinstance(v, float): return f"{v:,.{d}f}"
    return f"{v:,}"

def pct(before, after, lower_is_better=False):
    if before in (None, 0) or after is None: return "-"
    ch = (after - before) / before * 100
    return f"{ch:+.1f}%"

out = []
def H(s): out.append("\n" + s + "\n")
def T(header, rows, align=None):
    out.append("| " + " | ".join(header) + " |")
    out.append("|" + "|".join(["---:" if i else "---" for i in range(len(header))]) + "|")
    for r in rows: out.append("| " + " | ".join(str(x) for x in r) + " |")
    out.append("")

summary = {}
ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
out.append(f"# 측정 결과 (자동 생성: {ts})\n\n모든 수치는 실측값이며 rep=warmup 을 제외한 반복 측정의 **중앙값**이다. "
           "5회 측정값·최소·최대·표준편차는 각 절의 반복 측정 표에 있다. 생성: `bench/report.py`.\n")

# ---------- 1. 정합성 ----------
coh = group("coherence")
H("## 1. 정합성 지표 — 쿠폰 100개, 서로 다른 사용자 1,000명 (실험 coherence)")
for vus in [1000, 200, 10]:
    if not any((s, vus) in coh for s in STRATS): continue
    H(f"### 동시 사용자 {vus:,}명 (5회 반복, 값이 반복마다 다르면 `중앙값 [최소–최대]`)")
    rows = []
    for s in STRATS:
        rs = coh.get((s, vus))
        if not rs: continue
        def rng(path, integer=True):
            st = stats(rs, path)
            if st["min"] == st["max"]: return fmt(int(st["median"]) if integer else st["median"])
            return f"{fmt(int(st['median']))} [{fmt(int(st['min']))}–{fmt(int(st['max']))}]"
        ok = all(r["db"]["over_issue"] == 0 and r["db"]["dup_issue"] == 0 and r["db"]["resp_db_mismatch"] == 0 and r["db"]["stock_mismatch"] == 0 for r in rs)
        rows.append([LABEL[s], rng("issued"), rng("db.issues"), rng("db.issued_qty"), rng("db.over_issue"), rng("db.dup_issue"),
                     rng("db.resp_db_mismatch"), rng("db.stock_mismatch"), "✅ 성공" if ok else "❌ 실패"])
        summary.setdefault("coherence", {}).setdefault(str(vus), {})[s] = {"ok": ok, "issued": med(rs, "issued"), "db_issues": med(rs, "db.issues"),
            "issued_qty": med(rs, "db.issued_qty"), "over_issue_max": stats(rs, "db.over_issue")["max"], "dup_issue_max": stats(rs, "db.dup_issue")["max"]}
    T(["구현 방식", "성공 응답", "DB 발급 건수", "발급 수량(issued_quantity)", "초과 발급", "중복 발급", "응답-DB 불일치", "재고-발급 불일치", "정합성"], rows)

# ---------- 2. 성능 지표 ----------
PERF_KEYS = {"total": "total", "issued": "issued", "sold_out": "sold_out", "duplicate": "duplicate", "server_error": "server_error",
             "tps": "tps", "success_tps": "success_tps", "normal_rate": "normal_rate", "error_rate": "error_rate",
             "avg": "lat.avg", "p50": "lat.p(50)", "p95": "lat.p(95)", "p99": "lat.p(99)", "max": "lat.max",
             "acquire_avg_ms": "hikari.acquire_avg_ms", "pending_max": "hikari.pending_max",
             "row_lock_waits": "innodb.row_lock_waits", "row_lock_time_avg_ms": "innodb.row_lock_time_avg_ms",
             "conflicts": "app.optimistic_conflicts", "retries": "app.retries", "deadlocks": "innodb.deadlocks", "mysql_cpu_pct": "mysql.cpu_avg_pct"}
def perf_table(g, vus, title):
    H(title)
    for s in STRATS:
        rs = g.get((s, vus))
        if rs: summary.setdefault("perf", {}).setdefault(rs[0]["exp"], {}).setdefault(str(vus), {})[s] = {k: med(rs, p) for k, p in PERF_KEYS.items()}
    rows = []
    for s in STRATS + ([] if all((x, vus) in g for x in STRATS) else []):
        rs = g.get((s, vus))
        if not rs: continue
        rows.append([LABEL[s], fmt(int(med(rs, "total"))), fmt(int(med(rs, "issued"))), fmt(int(med(rs, "sold_out"))), fmt(int(med(rs, "duplicate"))),
                     fmt(int(med(rs, "server_error"))), fmt(med(rs, "tps")), fmt(med(rs, "success_tps")), fmt(med(rs, "normal_rate"), 2) + "%", fmt(med(rs, "error_rate"), 2) + "%"])
    T(["구현 방식", "전체 요청", "성공 발급", "품절 응답", "중복 차단", "서버 오류(5xx)", "전체 TPS", "성공 처리 TPS", "정상 종료율", "서버 오류율"], rows)
    rows = []
    for s in STRATS:
        rs = g.get((s, vus))
        if not rs: continue
        rows.append([LABEL[s], fmt(med(rs, "lat.avg")), fmt(med(rs, "lat.p(50)")), fmt(med(rs, "lat.p(95)")), fmt(med(rs, "lat.p(99)")), fmt(med(rs, "lat.max")),
                     fmt(med(rs, "lat_issued.p(95)")), fmt(med(rs, "lat_soldout.p(95)"))])
    T(["구현 방식", "평균(ms)", "p50", "p95", "p99", "최대", "발급 성공 p95", "품절 응답 p95"], rows)
    rows = []
    for s in STRATS:
        rs = g.get((s, vus))
        if not rs: continue
        rows.append([LABEL[s], fmt(med(rs, "hikari.acquire_avg_ms"), 2), fmt(med(rs, "hikari.acquire_max_ms")), fmt(med(rs, "hikari.active_max"), 0),
                     fmt(med(rs, "hikari.idle_min"), 0), fmt(med(rs, "hikari.pending_max"), 0),
                     fmt(med(rs, "mysql.sql_avg_ms"), 3), fmt(med(rs, "mysql.sql_max_ms"), 1),
                     fmt(med(rs, "innodb.row_lock_waits"), 0), fmt(med(rs, "innodb.row_lock_time_avg_ms"), 2), fmt(med(rs, "innodb.row_lock_time_ms"), 0)])
    T(["구현 방식", "커넥션 획득 평균(ms)", "획득 최대(ms)", "활성 max", "유휴 min", "대기 max", "SQL 평균(ms)", "SQL 최대(ms)", "행 잠금 대기 횟수", "행 잠금 대기 평균(ms)", "행 잠금 대기 합계(ms)"], rows)
    rows = []
    for s in STRATS:
        rs = g.get((s, vus))
        if not rs: continue
        rows.append([LABEL[s], fmt(med(rs, "app.optimistic_conflicts"), 0), fmt(med(rs, "app.retries"), 0), fmt(med(rs, "innodb.deadlocks"), 0), fmt(med(rs, "app.deadlocks"), 0),
                     fmt((med(rs, "app.process_cpu_avg") or 0) * 100, 1) + "%", fmt((med(rs, "app.system_cpu_avg") or 0) * 100, 1) + "%",
                     fmt(med(rs, "app.heap_used_max_mb"), 0) + " MB", fmt(med(rs, "mysql.cpu_avg_pct"), 1) + "%", fmt(med(rs, "mysql.mem_max_mb"), 0) + " MB"])
    T(["구현 방식", "낙관적 락 충돌", "재시도", "데드락(InnoDB)", "데드락(앱 감지)", "JVM CPU 평균", "시스템 CPU 평균", "JVM 힙 최대", "MySQL CPU 평균", "MySQL 메모리 최대"], rows)

H("## 2. 성능 지표")
out.append("전체 TPS = 전체 응답 수 / 테스트 시간, 성공 처리 TPS = 성공 발급 수 / 테스트 시간, 정상 종료율 = (발급 성공 + 품절 + 중복 차단) / 전체 요청 수, 서버 오류율 = 5xx / 전체 요청 수 × 100. "
           "coherence(요청 1,000건 고정)에서는 테스트 시간이 곧 1,000건 처리 시간이므로 성공 처리 TPS는 '100건을 얼마나 빨리 소진했나'를 뜻한다. "
           "1초 미만으로 끝나는 실행에서는 Prometheus(1초 스크레이프) 기반 지표(활성/대기 커넥션, CPU, 메모리, docker stats)가 0~1개 표본이라 신뢰도가 낮다. 지속 부하(sustained) 표를 우선 참고한다.\n")
for vus in [1000, 200]:
    if any((s, vus) in coh for s in STRATS): perf_table(coh, vus, f"### 2.{1 if vus==1000 else 2} coherence — 쿠폰 100개 / 요청 1,000건 / 동시 사용자 {vus:,}명")
sus = group("sustained")
for vus in [200, 1000]:
    if any((s, vus) in sus for s in STRATS): perf_table(sus, vus, f"### 2.{3 if vus==200 else 4} sustained — 재고 무제한(10,000,000) / 10초 지속 / 동시 사용자 {vus:,}명")
# 웹 UI(web/)용: 동시 사용자 단계별 중앙값 시계열
for exp, g in [("coherence", coh), ("sustained", sus)]:
    for (s, vus), rs in sorted(g.items(), key=lambda kv: kv[0][1]):
        summary.setdefault("series", {}).setdefault(exp, {}).setdefault(s, []).append({"vus": vus, **{k: med(rs, p) for k, p in PERF_KEYS.items()}})

# ---------- 3. 개선율 ----------
H("## 3. 개선율 계산")
out.append("공식: 처리량 개선율 = (후 TPS − 전 TPS)/전 TPS×100, 응답시간 감소율 = (전 p95 − 후 p95)/전 p95×100, 오류율 감소율 = (전 − 후)/전×100, 락 대기시간 감소율 = (전 − 후)/전×100. "
           "'변경 전'은 **정합성이 보장되는 첫 구현인 비관적 락**, '변경 후'는 최종 선택인 조건부 UPDATE 이다. 참고용으로 락 없음 → 조건부 UPDATE 도 함께 둔다(락 없음은 정합성이 깨지므로 성능 비교 대상이 아니다).\n")
def improve(g, vus, before, after, title):
    b, a = g.get((before, vus)), g.get((after, vus))
    if not b or not a: return
    H(title)
    def row(name, path, d=1, lower=False, unit=""):
        bv, av = med(b, path), med(a, path)
        if bv is None or av is None: return [name, "-", "-", "-"]
        if lower:
            ch = f"{(bv-av)/bv*100:+.1f}% 감소".replace("+", "-") if bv else "-"
            ch = ("-" if bv == 0 else f"{-(bv-av)/bv*100:+.1f}%")
        else:
            ch = pct(bv, av)
        return [name, fmt(bv, d) + unit, fmt(av, d) + unit, ch]
    rows = [row("전체 TPS", "tps"), row("성공 처리 TPS", "success_tps"), row("p50 응답시간", "lat.p(50)", 1, True, " ms"), row("p95 응답시간", "lat.p(95)", 1, True, " ms"),
            row("p99 응답시간", "lat.p(99)", 1, True, " ms")]
    be, ae = med(b, "error_rate"), med(a, "error_rate")
    rows.append(["서버 오류율", f"{fmt(be,2)}%", f"{fmt(ae,2)}%", f"{ae-be:+.2f}%p" + (f" ({-(be-ae)/be*100:+.1f}%)" if be else "")])
    rows.append(row("평균 행 잠금 대기시간", "innodb.row_lock_time_avg_ms", 2, True, " ms"))
    rows.append(row("행 잠금 대기 합계", "innodb.row_lock_time_ms", 0, True, " ms"))
    rows.append(row("커넥션 획득 평균", "hikari.acquire_avg_ms", 2, True, " ms"))
    bo, ao = stats(b, "db.over_issue")["max"], stats(a, "db.over_issue")["max"]
    rows.append(["초과 발급(최대)", fmt(bo), fmt(ao), "0건 달성" if ao == 0 else f"{ao}건"])
    bd, ad = stats(b, "db.dup_issue")["max"], stats(a, "db.dup_issue")["max"]
    rows.append(["중복 발급(최대)", fmt(bd), fmt(ad), "0건 달성" if ad == 0 else f"{ad}건"])
    T(["지표", f"변경 전 ({LABEL[before]})", f"변경 후 ({LABEL[after]})", "변화"], rows)
    if before == "no-lock":
        out.append("> 락 없음의 '성공 응답'은 초과 발급(900건)을 포함한 잘못된 성공이므로 성공 처리 TPS 행은 비교 의미가 없다. 정합성이 깨진 구현의 처리량은 개선 기준선이 될 수 없다.\n")
    summary.setdefault("improve", {})[f"{before}->{after}@{g[(before,vus)][0]['exp']}v{vus}"] = {r[0]: r[1:] for r in rows}
n = 0
for vus in [1000, 200]:
    n += 1; improve(coh, vus, "pessimistic", "conditional", f"### 3.{n} coherence, 동시 사용자 {vus:,}명: 비관적 락 → 조건부 UPDATE")
    n += 1; improve(coh, vus, "no-lock", "conditional", f"### 3.{n} coherence, 동시 사용자 {vus:,}명: 락 없음 → 조건부 UPDATE (참고)")
for vus in [200, 1000]:
    n += 1; improve(sus, vus, "pessimistic", "conditional", f"### 3.{n} sustained, 동시 사용자 {vus:,}명: 비관적 락 → 조건부 UPDATE")
    n += 1; improve(sus, vus, "optimistic", "conditional", f"### 3.{n} sustained, 동시 사용자 {vus:,}명: 낙관적 락 → 조건부 UPDATE")

# ---------- 4. 반복 측정 ----------
H("## 4. 반복 측정값 (5회 / 중앙값 / 최소 / 최대 / 표준편차 / 변동계수)")
def rep_table(g, path, name, d=1):
    rows = []
    for (s, vus) in sorted(g, key=lambda k: (STRATS.index(k[0]), k[1])):
        st = stats(g[(s, vus)], path)
        if not st: continue
        cv = st["stdev"] / st["mean"] * 100 if st["mean"] else 0
        rows.append([LABEL[s], f"{vus:,}", ", ".join(fmt(v, d) for v in st["values"]), fmt(st["median"], d), fmt(st["min"], d), fmt(st["max"], d), fmt(st["stdev"], d), f"{cv:.1f}%"])
    T(["구현 방식", "동시 사용자", f"{name} 측정값", "중앙값", "최소", "최대", "표준편차", "변동계수"], rows)
for exp, g in [("coherence", coh), ("sustained", sus)]:
    if not g: continue
    k = 1 if exp == 'coherence' else 2
    H(f"### 4.{k}.1 {exp} — 전체 TPS"); rep_table(g, "tps", "TPS")
    H(f"### 4.{k}.2 {exp} — p95 응답시간(ms)"); rep_table(g, "lat.p(95)", "p95")
    H(f"### 4.{k}.3 {exp} — p99 응답시간(ms)"); rep_table(g, "lat.p(99)", "p99")

# ---------- 5. 병목 ----------
H("## 5. 동시 사용자 수에 따른 병목 지표 (sustained, 중앙값)")
for s in STRATS:
    rows = []
    for (st, vus) in sorted(sus, key=lambda k: k[1]):
        if st != s: continue
        rs = sus[(st, vus)]
        rows.append([f"{vus:,}", fmt(med(rs, "tps")), fmt(med(rs, "success_tps")), fmt(med(rs, "lat.p(95)")), fmt(med(rs, "lat.p(99)")), fmt(med(rs, "hikari.acquire_avg_ms"), 2),
                     fmt(med(rs, "hikari.acquire_max_ms")), fmt(med(rs, "hikari.pending_max"), 0), fmt(med(rs, "innodb.row_lock_time_avg_ms"), 2), fmt(med(rs, "innodb.row_lock_waits"), 0),
                     fmt(med(rs, "app.optimistic_conflicts"), 0), fmt(med(rs, "app.retries"), 0), fmt(med(rs, "server_error"), 0), fmt((med(rs, "app.process_cpu_avg") or 0) * 100, 1) + "%", fmt(med(rs, "mysql.cpu_avg_pct"), 1) + "%",
                     fmt(med(rs, "db.stock_mismatch"), 0)])
    if rows:
        H(f"### {LABEL[s]}")
        T(["동시 사용자", "TPS", "성공 TPS", "p95(ms)", "p99(ms)", "커넥션 획득 평균(ms)", "획득 최대(ms)", "대기 커넥션 max", "행 잠금 대기 평균(ms)", "행 잠금 대기 횟수", "낙관적 충돌", "재시도", "5xx", "JVM CPU", "MySQL CPU", "재고-발급 불일치"], rows)

# 품절 vs 발급 가능
so = group("soldout")
if so:
    H("### 5.1 발급 가능 상태(sustained) vs 품절 상태(soldout) 처리 성능 (중앙값)")
    rows = []
    for vus in sorted({k[1] for k in so}):
        for s in STRATS:
            a, b = sus.get((s, vus)), so.get((s, vus))
            if not a or not b: continue
            rows.append([f"{vus:,}", LABEL[s], fmt(med(a, "tps")), fmt(med(b, "tps")), fmt(med(a, "lat.p(95)")), fmt(med(b, "lat.p(95)")),
                         fmt(med(a, "innodb.row_lock_waits"), 0), fmt(med(b, "innodb.row_lock_waits"), 0), fmt(med(a, "mysql.sql_avg_ms"), 3), fmt(med(b, "mysql.sql_avg_ms"), 3)])
    T(["동시 사용자", "구현 방식", "TPS(발급 가능)", "TPS(품절)", "p95 발급 가능", "p95 품절", "행 잠금 대기(발급 가능)", "행 잠금 대기(품절)", "SQL 평균 ms(발급 가능)", "SQL 평균 ms(품절)"], rows)

# 풀 크기
pools = {}
for r in runs:
    if r["exp"] == "poolsize":
        pools.setdefault((r["strategy"], r["pool"]), []).append(r)
if pools:
    H("### 5.2 HikariCP 풀 크기와 처리량 (sustained 조건, 동시 사용자 200명, 중앙값)")
    rows = []
    for (s, pool) in sorted(pools, key=lambda k: (STRATS.index(k[0]), k[1])):
        rs = pools[(s, pool)]
        rows.append([LABEL[s], pool, fmt(med(rs, "tps")), fmt(med(rs, "lat.p(95)")), fmt(med(rs, "lat.p(99)")), fmt(med(rs, "hikari.acquire_avg_ms"), 2), fmt(med(rs, "hikari.pending_max"), 0),
                     fmt(med(rs, "innodb.row_lock_time_avg_ms"), 2), fmt(med(rs, "innodb.row_lock_waits"), 0), fmt(med(rs, "mysql.cpu_avg_pct"), 1) + "%"])
    T(["구현 방식", "풀 크기", "TPS", "p95(ms)", "p99(ms)", "커넥션 획득 평균(ms)", "대기 커넥션 max", "행 잠금 대기 평균(ms)", "행 잠금 대기 횟수", "MySQL CPU"], rows)

# 중복 요청
dup = group("duplicate")
if dup:
    H("## 6. 중복 요청 시나리오 — 사용자 1,000명이 각 2회 요청(2,000건), 동시 사용자 1,000명, 쿠폰 100개")
    rows = []
    for s in STRATS:
        rs = dup.get((s, 1000))
        if not rs: continue
        st = lambda p: stats(rs, p)
        rows.append([LABEL[s], fmt(int(med(rs, "total"))), fmt(int(med(rs, "issued"))), fmt(int(med(rs, "duplicate"))), fmt(int(med(rs, "sold_out"))), fmt(int(med(rs, "server_error"))),
                     fmt(st("db.issues")["max"]), fmt(st("db.dup_issue")["max"]), fmt(st("db.over_issue")["max"]), fmt(med(rs, "tps")), fmt(med(rs, "lat.p(95)"))])
    T(["구현 방식", "전체 요청", "성공 응답", "중복 차단(409)", "품절(410)", "5xx", "DB 발급 건수(max)", "중복 발급(max)", "초과 발급(max)", "TPS", "p95(ms)"], rows)
dop = group("dupopen")
if dop:
    H("### 6.1 재고가 남아 있는 상태의 중복 요청 — 쿠폰 10,000,000개, 사용자 1,000명 × 2회, 동시 사용자 1,000명")
    out.append("품절 빠른 경로가 개입하지 않으므로 2번째 요청은 모두 UNIQUE 제약에 걸려야 한다(기대: 성공 1,000 / 중복 차단 1,000 / DB 1,000건).\n")
    rows = []
    for s in STRATS:
        rs = dop.get((s, 1000))
        if not rs: continue
        st = lambda p: stats(rs, p)
        rows.append([LABEL[s], fmt(int(med(rs, "total"))), fmt(int(med(rs, "issued"))), fmt(int(med(rs, "duplicate"))), fmt(int(med(rs, "sold_out"))), fmt(int(med(rs, "server_error"))),
                     fmt(st("db.issues")["max"]), fmt(st("db.distinct_users")["min"]), fmt(st("db.dup_issue")["max"]), fmt(st("db.stock_mismatch")["max"]), fmt(med(rs, "tps")), fmt(med(rs, "lat.p(95)"))])
    T(["구현 방식", "전체 요청", "성공 응답", "중복 차단(409)", "품절(410)", "5xx", "DB 발급 건수(max)", "고유 사용자(min)", "중복 발급(max)", "재고-발급 불일치(max)", "TPS", "p95(ms)"], rows)
nu = {}
for r in runs:
    if r["exp"] == "nounique": nu.setdefault(r["strategy"], []).append(r)
nuo = {}
for r in runs:
    if r["exp"] == "nouniqueopen": nuo.setdefault(r["strategy"], []).append(r)
if nuo:
    H("### 6.2 UNIQUE 제약 제거 + 재고 남음 (6.1 과 같은 부하) — 락 방식이 중복을 막아 주는가?")
    rows = []
    for s in STRATS:
        rs = nuo.get(s)
        if not rs: continue
        rows.append([LABEL[s], fmt(int(med(rs, "issued"))), fmt(int(med(rs, "duplicate"))), fmt(stats(rs, "db.issues")["max"]), fmt(stats(rs, "db.distinct_users")["min"]),
                     ", ".join(str(int(v)) for v in stats(rs, "db.dup_issue")["values"]), fmt(stats(rs, "db.dup_issue")["max"])])
    T(["구현 방식", "성공 응답", "중복 차단(409)", "DB 발급 건수(max)", "고유 사용자(min)", "중복 발급(5회 각각)", "중복 발급(max)"], rows)
if nu:
    H("### 6.3 UNIQUE 제약 제거 + 쿠폰 100개 (6절 본 시나리오와 같은 부하)")
    rows = []
    for s in STRATS:
        rs = nu.get(s)
        if not rs: continue
        rows.append([LABEL[s], fmt(int(med(rs, "issued"))), fmt(int(med(rs, "duplicate"))), fmt(stats(rs, "db.issues")["max"]), fmt(stats(rs, "db.distinct_users")["min"]),
                     fmt(stats(rs, "db.dup_issue")["max"]), fmt(stats(rs, "db.over_issue")["max"])])
    T(["구현 방식", "성공 응답", "중복 차단(409)", "DB 발급 건수(max)", "고유 사용자(min)", "중복 발급(max)", "초과 발급(max)"], rows)

# ---------- charts ----------
def bar_by_strategy(g, vus, path, title, ylabel, fname, d=0):
    ks = [s for s in STRATS if (s, vus) in g]
    if not ks: return
    vals = [med(g[(s, vus)], path) for s in ks]
    mins = [stats(g[(s, vus)], path)["min"] for s in ks]; maxs = [stats(g[(s, vus)], path)["max"] for s in ks]
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    x = range(len(ks))
    ax.bar(x, vals, color=[COLOR[s] for s in ks], width=0.55, yerr=[[v - m for v, m in zip(vals, mins)], [m - v for v, m in zip(vals, maxs)]],
           capsize=3, error_kw={"elinewidth": 1, "ecolor": "#52514e"})
    for i, v in enumerate(vals): ax.text(i, v, f"{v:,.{d}f}", ha="center", va="bottom", fontsize=8, color="#0b0b0b")
    ax.set_xticks(list(x)); ax.set_xticklabels([LABEL[s] for s in ks]); ax.set_ylabel(ylabel); ax.set_title(title, loc="left", fontsize=10)
    ax.set_ylim(0, max(maxs) * 1.18); ax.grid(axis="x", visible=False)
    fig.tight_layout(); fig.savefig(f"docs/charts/{fname}"); plt.close(fig)

def grouped_bars(g, vus, paths, labels, title, ylabel, fname):
    ks = [s for s in STRATS if (s, vus) in g]
    if not ks: return
    fig, ax = plt.subplots(figsize=(6.4, 3.6)); w = 0.8 / len(paths)
    for j, (p, lab) in enumerate(zip(paths, labels)):
        vals = [med(g[(s, vus)], p) for s in ks]
        xs = [i + (j - (len(paths) - 1) / 2) * w for i in range(len(ks))]
        ax.bar(xs, vals, width=w - 0.04, color=[COLOR[s] for s in ks], alpha=1.0 if j == 0 else 0.45, hatch=None if j == 0 else "///", edgecolor="white", linewidth=0.5)
        for xx, v in zip(xs, vals): ax.text(xx, v, f"{v:,.0f}", ha="center", va="bottom", fontsize=7)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(facecolor="#8a8a85", label=labels[0]), Patch(facecolor="#8a8a85", alpha=0.45, hatch="///", edgecolor="white", label=labels[1])], frameon=False)
    ax.set_xticks(range(len(ks))); ax.set_xticklabels([LABEL[s] for s in ks]); ax.set_ylabel(ylabel); ax.set_title(title, loc="left", fontsize=10)
    ax.grid(axis="x", visible=False); fig.tight_layout(); fig.savefig(f"docs/charts/{fname}"); plt.close(fig)

def lines_vs_vus(g, path, title, ylabel, fname, logy=False):
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    for s in STRATS:
        pts = sorted((vus, med(rs, path), stats(rs, path)["min"], stats(rs, path)["max"]) for (st, vus), rs in g.items() if st == s and med(rs, path) is not None)
        if not pts: continue
        xs = [p[0] for p in pts]
        ax.plot(xs, [p[1] for p in pts], marker="o", ms=4, lw=2, color=COLOR[s], label=LABEL[s])
        ax.fill_between(xs, [p[2] for p in pts], [p[3] for p in pts], color=COLOR[s], alpha=0.12, lw=0)
        ax.annotate(LABEL[s], (xs[-1], pts[-1][1]), textcoords="offset points", xytext=(4, 0), fontsize=7, color=COLOR[s])
    ax.set_xscale("log"); ax.set_xticks([10, 50, 100, 200, 500, 1000]); ax.set_xticklabels(["10", "50", "100", "200", "500", "1,000"])
    if logy: ax.set_yscale("log")
    ax.set_xlabel("동시 사용자 수 (VU)"); ax.set_ylabel(ylabel); ax.set_title(title, loc="left", fontsize=10)
    if ax.get_legend_handles_labels()[0]: ax.legend(frameon=False, fontsize=8)
    fig.tight_layout(); fig.savefig(f"docs/charts/{fname}"); plt.close(fig)

def prom_series(query, start, end, step="1"):
    try:
        q = urllib.parse.urlencode({"query": query, "start": start, "end": end, "step": step})
        r = json.load(urllib.request.urlopen(f"http://localhost:9090/api/v1/query_range?{q}", timeout=10))
        res = r["data"]["result"]
        if not res: return [], []
        vals = res[0]["values"]
        return [float(t) for t, _ in vals], [float(v) if v != "NaN" else 0 for _, v in vals]
    except Exception as e:
        return [], []

def timeseries_chart(exp_runs, queries, title, ylabel, fname, unit=1.0):
    """exp_runs: 전략별 대표 실행(dict strategy→run). 각 실행 구간을 이어 붙여 한 그림에 그린다."""
    if not exp_runs: return
    fig, axes = plt.subplots(1, len(exp_runs), figsize=(2.2 * len(exp_runs) + 1.5, 3.4), sharey=True)
    if len(exp_runs) == 1: axes = [axes]
    for ax, (s, r) in zip(axes, exp_runs.items()):
        for q, lab, ls in queries:
            t, v = prom_series(q, r["start"] - 1, r["end"] + 1)
            if t: ax.plot([x - r["start"] for x in t], [y * unit for y in v], lw=1.8, ls=ls, color=COLOR[s], alpha=1.0 if ls == "-" else 0.6, label=lab)
        ax.set_title(LABEL[s], fontsize=9, color=COLOR[s]); ax.set_xlabel("경과(초)")
        if ax is axes[0]: ax.set_ylabel(ylabel); ax.legend(frameon=False, fontsize=7)
    fig.suptitle(title, x=0.01, ha="left", fontsize=10); fig.tight_layout(); fig.savefig(f"docs/charts/{fname}"); plt.close(fig)

def stacked_mix(g, vus, title, fname):
    ks = [s for s in STRATS if (s, vus) in g]
    if not ks: return
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    parts = [("issued", "발급 성공", "#1baf7a"), ("sold_out", "품절", "#8a8a85"), ("duplicate", "중복 차단", "#2a78d6"), ("server_error", "서버 오류", "#e34948")]
    bottom = [0] * len(ks)
    for p, lab, c in parts:
        vals = [med(g[(s, vus)], p) / med(g[(s, vus)], "total") * 100 for s in ks]
        ax.barh(range(len(ks)), vals, left=bottom, color=c, label=lab, height=0.55, edgecolor="white", linewidth=1)
        for i, (b, v) in enumerate(zip(bottom, vals)):
            if v >= 4: ax.text(b + v / 2, i, f"{v:.1f}%", ha="center", va="center", fontsize=7, color="white")
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_yticks(range(len(ks))); ax.set_yticklabels([LABEL[s] for s in ks]); ax.set_xlim(0, 100); ax.set_xlabel("응답 비율(%)")
    ax.set_title(title, loc="left", fontsize=10); ax.legend(frameon=False, fontsize=7, ncol=4, loc="lower center", bbox_to_anchor=(0.5, 1.0)); ax.grid(axis="y", visible=False)
    fig.tight_layout(); fig.savefig(f"docs/charts/{fname}"); plt.close(fig)

if coh:
    bar_by_strategy(coh, 1000, "tps", "구현 방식별 전체 TPS — coherence, 동시 사용자 1,000명 (중앙값, 오차선=최소–최대)", "TPS", "tps_by_strategy_coherence_v1000.png")
    grouped_bars(coh, 1000, ["lat.p(95)", "lat.p(99)"], ["p95", "p99"], "구현 방식별 p95·p99 응답시간 — coherence, 동시 사용자 1,000명 (중앙값)", "ms", "latency_p95_p99_coherence_v1000.png")
    lines_vs_vus(coh, "tps", "동시 사용자 증가에 따른 전체 TPS — coherence (중앙값, 음영=최소–최대)", "TPS", "tps_vs_vus_coherence.png")
    lines_vs_vus(coh, "lat.p(95)", "동시 사용자 증가에 따른 p95 — coherence (중앙값, 음영=최소–최대)", "p95 (ms)", "p95_vs_vus_coherence.png", logy=True)
    stacked_mix(coh, 1000, "성공·품절·중복·서버 오류 응답 비율 — coherence, 동시 사용자 1,000명", "response_mix_coherence_v1000.png")
    # 정합성 비교
    ks = [s for s in STRATS if (s, 1000) in coh]
    fig, ax = plt.subplots(figsize=(6.4, 3.4)); w = 0.38
    over = [stats(coh[(s, 1000)], "db.over_issue")["max"] for s in ks]; mism = [stats(coh[(s, 1000)], "db.stock_mismatch")["max"] for s in ks]
    ax.bar([i - w / 2 for i in range(len(ks))], over, w, color="#e34948", label="초과 발급(건)")
    ax.bar([i + w / 2 for i in range(len(ks))], mism, w, color="#eda100", label="재고-발급 불일치(건)")
    for i in range(len(ks)):
        ax.text(i - w / 2, over[i], f"{over[i]:,}", ha="center", va="bottom", fontsize=8); ax.text(i + w / 2, mism[i], f"{mism[i]:,}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(range(len(ks))); ax.set_xticklabels([LABEL[s] for s in ks]); ax.set_ylabel("건 (5회 중 최대)")
    ax.set_title("개선 전후 정합성 — 쿠폰 100개 / 요청 1,000건 / 동시 사용자 1,000명", loc="left", fontsize=10); ax.legend(frameon=False, fontsize=8); ax.grid(axis="x", visible=False)
    fig.tight_layout(); fig.savefig("docs/charts/integrity_coherence_v1000.png"); plt.close(fig)
if sus:
    bar_by_strategy(sus, 200, "tps", "구현 방식별 전체 TPS — sustained(재고 무제한), 동시 사용자 200명", "TPS", "tps_by_strategy_sustained_v200.png")
    bar_by_strategy(sus, 1000, "tps", "구현 방식별 전체 TPS — sustained(재고 무제한), 동시 사용자 1,000명", "TPS", "tps_by_strategy_sustained_v1000.png")
    grouped_bars(sus, 200, ["lat.p(95)", "lat.p(99)"], ["p95", "p99"], "구현 방식별 p95·p99 응답시간 — sustained, 동시 사용자 200명 (중앙값)", "ms", "latency_p95_p99_sustained_v200.png")
    grouped_bars(sus, 1000, ["lat.p(95)", "lat.p(99)"], ["p95", "p99"], "구현 방식별 p95·p99 응답시간 — sustained, 동시 사용자 1,000명 (중앙값)", "ms", "latency_p95_p99_sustained_v1000.png")
    lines_vs_vus(sus, "tps", "동시 사용자 증가에 따른 전체 TPS — sustained (중앙값, 음영=최소–최대)", "TPS", "tps_vs_vus_sustained.png")
    lines_vs_vus(sus, "lat.p(95)", "동시 사용자 증가에 따른 p95 — sustained (중앙값, 음영=최소–최대)", "p95 (ms)", "p95_vs_vus_sustained.png", logy=True)
    lines_vs_vus(sus, "hikari.acquire_avg_ms", "동시 사용자 증가에 따른 DB 커넥션 획득 대기(평균) — sustained", "ms", "hikari_acquire_vs_vus_sustained.png", logy=True)
    lines_vs_vus(sus, "innodb.row_lock_time_avg_ms", "동시 사용자 증가에 따른 행 잠금 대기(평균) — sustained", "ms", "rowlock_vs_vus_sustained.png")
    lines_vs_vus({k: v for k, v in sus.items() if k[0] == "optimistic"}, "app.retries", "동시 사용자 증가에 따른 낙관적 락 재시도 횟수(10초) — sustained", "재시도", "retries_vs_vus_sustained.png")
    stacked_mix(sus, 1000, "성공·품절·중복·서버 오류 응답 비율 — sustained, 동시 사용자 1,000명", "response_mix_sustained_v1000.png")
    rep1 = {s: sorted(sus[(s, 200)], key=lambda r: r["start"])[0] for s in STRATS if (s, 200) in sus}
    timeseries_chart(rep1, [("hikaricp_connections_active", "active", "-"), ("hikaricp_connections_pending", "pending", "--")],
                     "시간대별 DB 커넥션 사용량 — sustained, 동시 사용자 200명, 1회차 (풀 20)", "커넥션 수", "db_connections_timeseries_v200.png")
    timeseries_chart(rep1, [("rate(mysql_global_status_innodb_row_lock_time[2s])", "row_lock_time (ms/s)", "-")],
                     "시간대별 InnoDB 행 잠금 대기시간 — sustained, 동시 사용자 200명, 1회차", "ms / s", "rowlock_timeseries_v200.png")
    rep1k = {s: sorted(sus[(s, 1000)], key=lambda r: r["start"])[0] for s in STRATS if (s, 1000) in sus}
    if rep1k:
        timeseries_chart(rep1k, [("hikaricp_connections_active", "active", "-"), ("hikaricp_connections_pending", "pending", "--")],
                         "시간대별 DB 커넥션 사용량 — sustained, 동시 사용자 1,000명, 1회차 (풀 20)", "커넥션 수", "db_connections_timeseries_v1000.png")
        timeseries_chart(rep1k, [("rate(mysql_global_status_innodb_row_lock_time[2s])", "row_lock_time (ms/s)", "-")],
                         "시간대별 InnoDB 행 잠금 대기시간 — sustained, 동시 사용자 1,000명, 1회차", "ms / s", "rowlock_timeseries_v1000.png")
if pools:
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    for s in STRATS:
        pts = sorted((pool, med(rs, "tps")) for (st, pool), rs in pools.items() if st == s)
        if pts: ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", lw=2, color=COLOR[s], label=LABEL[s])
    ax.set_xticks([10, 20, 50]); ax.set_xlabel("HikariCP maximum-pool-size"); ax.set_ylabel("TPS"); ax.set_title("HikariCP 풀 크기와 처리량 — 동시 사용자 200명, 재고 무제한", loc="left", fontsize=10)
    ax.legend(frameon=False); fig.tight_layout(); fig.savefig("docs/charts/poolsize_tps.png"); plt.close(fig)

open("docs/results.md", "w").write("\n".join(out))
json.dump(summary, open("results/summary.json", "w"), ensure_ascii=False, indent=1)
print("wrote docs/results.md,", len(glob.glob("docs/charts/*.png")), "charts, runs:", len(runs))
