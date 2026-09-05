"""한 번의 실행 결과를 원시 파일들에서 모아 JSON 한 줄로 출력한다 (stdlib only)."""
import argparse, json, re, statistics, urllib.request, urllib.parse

p = argparse.ArgumentParser()
for k in ("exp", "tag", "id", "strategy", "vus", "rep", "start", "end", "qty", "mode", "pool", "raw"):
    p.add_argument("--" + k, required=True)
a = p.parse_args()
raw = f"{a.raw}/{a.id}"

def kv_tsv(path):
    d = {}
    for line in open(path):
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 2:
            try: d[parts[0]] = float(parts[1])
            except ValueError: d[parts[0]] = parts[1]
    return d

def prom_text(path):
    d = {}
    for line in open(path):
        if line.startswith("#"): continue
        m = re.match(r'^([a-zA-Z_:]+)(\{[^}]*\})?\s+(\S+)', line)
        if m: d[m.group(1) + (m.group(2) or "")] = float(m.group(3))
    return d

def prom_sum(d, name, **tags):
    tot = 0.0
    for k, v in d.items():
        if k.startswith(name) and all(f'{t}="{val}"' in k for t, val in tags.items()):
            tot += v
    return tot

def delta(after, before, key):
    return (after.get(key, 0) or 0) - (before.get(key, 0) or 0)

k6 = json.load(open(f"{raw}.k6.json"))
m = k6["metrics"]
def mv(name, key, default=None):
    return m.get(name, {}).get("values", {}).get(key, default)
dur_s = k6["state"]["testRunDurationMs"] / 1000.0
total = mv("http_reqs", "count", 0)
issued = mv("issued", "count", 0); sold = mv("sold_out", "count", 0)
dup = mv("duplicate", "count", 0); err5 = mv("server_error", "count", 0); other = mv("other", "count", 0)

before_db, after_db = kv_tsv(f"{raw}.before.mysql.tsv"), kv_tsv(f"{raw}.after.mysql.tsv")
before_app, after_app = prom_text(f"{raw}.before.app.prom"), prom_text(f"{raw}.after.app.prom")

strategy_tag = a.strategy.upper().replace("-", "_")
acq_sum = prom_sum(after_app, "hikaricp_connections_acquire_seconds_sum") - prom_sum(before_app, "hikaricp_connections_acquire_seconds_sum")
acq_cnt = prom_sum(after_app, "hikaricp_connections_acquire_seconds_count") - prom_sum(before_app, "hikaricp_connections_acquire_seconds_count")
conflicts = prom_sum(after_app, "coupon_optimistic_conflict_total", strategy=strategy_tag) - prom_sum(before_app, "coupon_optimistic_conflict_total", strategy=strategy_tag)
retries = prom_sum(after_app, "coupon_retry_total", strategy=strategy_tag) - prom_sum(before_app, "coupon_retry_total", strategy=strategy_tag)
app_deadlocks = prom_sum(after_app, "coupon_deadlock_total", strategy=strategy_tag) - prom_sum(before_app, "coupon_deadlock_total", strategy=strategy_tag)

# MySQL performance_schema digest (실행 구간 동안 TRUNCATE 후 누적)
sqls = []
for line in open(f"{raw}.sql.tsv"):
    f = line.rstrip("\n").split("\t")
    if len(f) >= 7 and f[0] not in ("NULL",) and not f[0].startswith(("TRUNCATE", "SHOW", "SELECT NAME", "SELECT COUNT")):
        sqls.append({"sql": f[0][:90], "count": int(f[1]), "avg_ms": float(f[2]), "max_ms": float(f[3]), "lock_ms": float(f[4]), "rows": int(f[5]), "errors": int(f[6])})
app_sqls = [s for s in sqls if s["sql"].startswith(("SELECT `issued_quantity`", "INSERT", "UPDATE"))]
sql_avg = (sum(s["avg_ms"] * s["count"] for s in app_sqls) / sum(s["count"] for s in app_sqls)) if app_sqls else None
sql_max = max((s["max_ms"] for s in app_sqls), default=None)

v = open(f"{raw}.verify.tsv").read().split()
db_issues, db_distinct, db_issued_qty, db_total = (int(x) for x in v[:4])

# docker stats 샘플 (MySQL 컨테이너)
cpu, mem = [], []
for line in open(f"{raw}.docker.tsv"):
    line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)  # docker stats 스트림의 ANSI 커서 제어 제거
    f = line.strip().split("\t")
    if len(f) == 2 and f[0].endswith("%"):
        try:
            cpu.append(float(f[0].rstrip("%")))
            mu = f[1].split("/")[0].strip()
            num = float(re.match(r"[\d.]+", mu).group()); unit = mu.lstrip("0123456789.")
            mem.append(num * {"B": 1, "KiB": 2**10, "MiB": 2**20, "GiB": 2**30}.get(unit, 1))
        except Exception: pass

def prom_range(query, fn):
    try:
        q = urllib.parse.urlencode({"query": query, "start": a.start, "end": a.end, "step": "1"})
        r = json.load(urllib.request.urlopen(f"http://localhost:9090/api/v1/query_range?{q}", timeout=5))
        vals = [float(x[1]) for s in r["data"]["result"] for x in s["values"] if x[1] != "NaN"]
        return fn(vals) if vals else None
    except Exception:
        return None

rec = {
    "exp": a.exp, "tag": a.tag, "id": a.id, "strategy": a.strategy, "vus": int(a.vus), "rep": a.rep,
    "qty": int(a.qty), "mode": a.mode, "pool": int(a.pool), "start": float(a.start), "end": float(a.end),
    "duration_s": round(dur_s, 3),
    "total": int(total), "issued": int(issued), "sold_out": int(sold), "duplicate": int(dup), "server_error": int(err5), "other": int(other),
    "tps": round(total / dur_s, 2) if dur_s else None,
    "success_tps": round(issued / dur_s, 2) if dur_s else None,
    "normal_rate": round((issued + sold + dup) / total * 100, 3) if total else None,
    "error_rate": round(err5 / total * 100, 3) if total else None,
    "lat": {k: round(mv("http_req_duration", k, 0), 3) for k in ("avg", "min", "med", "max", "p(50)", "p(90)", "p(95)", "p(99)")},
    "lat_issued": {k: round(mv("issued_duration", k, 0), 3) for k in ("avg", "med", "p(95)", "p(99)", "max")},
    "lat_soldout": {k: round(mv("sold_out_duration", k, 0), 3) for k in ("avg", "med", "p(95)", "p(99)", "max")},
    "db": {"issues": db_issues, "distinct_users": db_distinct, "issued_qty": db_issued_qty, "total_qty": db_total,
           "over_issue": max(0, db_issues - db_total), "dup_issue": db_issues - db_distinct,
           "resp_db_mismatch": int(issued) - db_issues, "stock_mismatch": db_issues - db_issued_qty},
    "innodb": {"row_lock_waits": delta(after_db, before_db, "Innodb_row_lock_waits"),
               "row_lock_time_ms": delta(after_db, before_db, "Innodb_row_lock_time"),
               "row_lock_time_max_ms": after_db.get("Innodb_row_lock_time_max"),
               "deadlocks": delta(after_db, before_db, "lock_deadlocks"), "lock_timeouts": delta(after_db, before_db, "lock_timeouts"),
               "com_select": delta(after_db, before_db, "Com_select"), "com_insert": delta(after_db, before_db, "Com_insert"),
               "com_update": delta(after_db, before_db, "Com_update"), "com_commit": delta(after_db, before_db, "Com_commit"),
               "com_rollback": delta(after_db, before_db, "Com_rollback")},
    "hikari": {"acquire_avg_ms": round(acq_sum / acq_cnt * 1000, 3) if acq_cnt else None,
               "acquire_max_ms": round(prom_sum(after_app, "hikaricp_connections_acquire_seconds_max") * 1000, 3),
               "acquire_count": acq_cnt,
               "pending_max": prom_range("hikaricp_connections_pending", max),
               "active_max": prom_range("hikaricp_connections_active", max),
               "active_avg": prom_range("hikaricp_connections_active", statistics.fmean),
               "idle_min": prom_range("hikaricp_connections_idle", min)},
    "app": {"optimistic_conflicts": conflicts, "retries": retries, "deadlocks": app_deadlocks,
            "process_cpu_avg": prom_range("process_cpu_usage", statistics.fmean), "process_cpu_max": prom_range("process_cpu_usage", max),
            "system_cpu_avg": prom_range("system_cpu_usage", statistics.fmean),
            "heap_used_max_mb": (lambda x: round(x / 2**20, 1) if x else None)(prom_range('sum(jvm_memory_used_bytes{area="heap"})', max))},
    "mysql": {"cpu_avg_pct": round(statistics.fmean(cpu), 1) if cpu else None, "cpu_max_pct": max(cpu) if cpu else None,
              "mem_max_mb": round(max(mem) / 2**20, 1) if mem else None,
              "threads_running_max": prom_range("mysql_global_status_threads_running", max),
              "sql_avg_ms": round(sql_avg, 3) if sql_avg is not None else None, "sql_max_ms": sql_max, "sql": app_sqls},
}
rec["innodb"]["row_lock_time_avg_ms"] = round(rec["innodb"]["row_lock_time_ms"] / rec["innodb"]["row_lock_waits"], 3) if rec["innodb"]["row_lock_waits"] else 0.0
print(json.dumps(rec, ensure_ascii=False))
