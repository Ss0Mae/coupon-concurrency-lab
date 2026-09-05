#!/usr/bin/env bash
# 실험 드라이버. usage: bench/run.sh <coherence|sustained|soldout|duplicate|poolsize|nounique> [REPS=5 LEVELS=".." STRATS=".."]
# 각 실행: DB 초기화 → 스냅샷(before) → k6 → 스냅샷(after) → DB 검증 → SQL 통계 → collect.py 가 runs.jsonl 에 1줄 기록
set -euo pipefail
cd "$(dirname "$0")/.."
EXP=${1:?experiment name}
# macOS 는 k6 가 닫은 소켓이 TIME_WAIT(15초)로 남아 임시 포트(약 16k)를 소진하면
# 다음 실행의 mysql/k6 연결이 errno 49 로 실패한다 → 연결 재시도 + 실행 전 TIME_WAIT 배수 대기
mq() { local i; for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
         mysql -h127.0.0.1 -P3306 -uroot -proot -Dcoupon "$@" 2> >(grep -v "Using a password" >&2) && return 0; sleep 5; done; return 1; }
MYSQL=mq
wait_ports() { local n; while n=$(netstat -an -p tcp | grep -c TIME_WAIT); [ "$n" -gt "${TW_LIMIT:-3000}" ]; do sleep 2; done; }
STRATS_ALL="no-lock pessimistic optimistic conditional"
REPS=${REPS:-5}
case $EXP in
  coherence) QTY=100;      MODE=iterations; ITERATIONS=1000; DURATION=0;   USERS=0;    LEVELS=${LEVELS:-"10 50 100 200 500 1000"};;
  sustained) QTY=10000000; MODE=duration;   ITERATIONS=0;    DURATION=10s; USERS=0;    LEVELS=${LEVELS:-"10 50 100 200 500 1000"};;
  soldout)   QTY=0;        MODE=duration;   ITERATIONS=0;    DURATION=10s; USERS=0;    LEVELS=${LEVELS:-"100 1000"};;
  duplicate) QTY=100;      MODE=iterations; ITERATIONS=2000; DURATION=0;   USERS=1000; LEVELS=${LEVELS:-"1000"};;
  poolsize)  QTY=10000000; MODE=duration;   ITERATIONS=0;    DURATION=10s; USERS=0;    LEVELS=${LEVELS:-"200"}; STRATS_ALL="pessimistic conditional";;
  nounique)  QTY=100;      MODE=iterations; ITERATIONS=2000; DURATION=0;   USERS=1000; LEVELS=${LEVELS:-"1000"}; STRATS_ALL="no-lock conditional";;
  dupopen)   QTY=10000000; MODE=iterations; ITERATIONS=2000; DURATION=0;   USERS=1000; LEVELS=${LEVELS:-"1000"};;
  nouniqueopen) QTY=10000000; MODE=iterations; ITERATIONS=2000; DURATION=0; USERS=1000; LEVELS=${LEVELS:-"1000"}; STRATS_ALL="no-lock conditional";;
  *) echo "unknown experiment $EXP"; exit 1;;
esac
STRATS=${STRATS:-$STRATS_ALL}
POOL=${HIKARI_POOL_SIZE:-20}
TAG=${TAG:-}          # 결과 구분용 자유 태그(예: pool10)
OUT=results/$EXP; mkdir -p $OUT/raw

reset_db() {
  $MYSQL -e "TRUNCATE coupon_issue; UPDATE coupon SET total_quantity=$QTY, issued_quantity=0, version=0 WHERE id=1; TRUNCATE performance_schema.events_statements_summary_by_digest;"
}
snapshot() {
  $MYSQL -N -e "SHOW GLOBAL STATUS WHERE Variable_name IN ('Innodb_row_lock_waits','Innodb_row_lock_time','Innodb_row_lock_time_max','Innodb_row_lock_current_waits','Threads_connected','Threads_running','Com_select','Com_insert','Com_update','Com_commit','Com_rollback','Questions'); SELECT name, count FROM information_schema.INNODB_METRICS WHERE name IN ('lock_deadlocks','lock_timeouts');" > "$1.mysql.tsv"
  curl -s localhost:8080/actuator/prometheus | grep -E '^(coupon_|hikaricp_connections|http_server_requests_seconds_(count|sum)|jvm_memory_used_bytes|process_cpu_usage|system_cpu_usage)' > "$1.app.prom"
}
one_run() {
  local strategy=$1 vus=$2 rep=$3
  local id="${EXP}${TAG:+_$TAG}_${strategy}_v${vus}_r${rep}"
  wait_ports; reset_db; sleep 0.3
  snapshot "$OUT/raw/$id.before"
  docker stats --format '{{.CPUPerc}}\t{{.MemUsage}}' coupon-mysql > "$OUT/raw/$id.docker.tsv" 2>/dev/null &
  local dstat=$!
  local start end
  start=$(python3 -c 'import time;print(time.time())')
  STRATEGY=$strategy VUS=$vus MODE=$MODE ITERATIONS=$ITERATIONS DURATION=$DURATION USERS=$USERS OUT="$OUT/raw/$id.k6.json" \
    k6 run --quiet k6/issue.js > "$OUT/raw/$id.k6.log" 2>&1 || echo "k6 exit $? ($id)"
  end=$(python3 -c 'import time;print(time.time())')
  kill $dstat 2>/dev/null || true
  snapshot "$OUT/raw/$id.after"
  $MYSQL -N -e "SELECT COUNT(*), COUNT(DISTINCT user_id), (SELECT issued_quantity FROM coupon WHERE id=1), (SELECT total_quantity FROM coupon WHERE id=1) FROM coupon_issue" > "$OUT/raw/$id.verify.tsv"
  $MYSQL -N -e "SELECT DIGEST_TEXT, COUNT_STAR, ROUND(AVG_TIMER_WAIT/1e9,3), ROUND(MAX_TIMER_WAIT/1e9,3), ROUND(SUM_LOCK_TIME/1e9,3), SUM_ROWS_AFFECTED, SUM_ERRORS FROM performance_schema.events_statements_summary_by_digest WHERE SCHEMA_NAME='coupon' ORDER BY COUNT_STAR DESC LIMIT 12" > "$OUT/raw/$id.sql.tsv"
  .venv/bin/python bench/collect.py --exp "$EXP" --tag "$TAG" --id "$id" --strategy "$strategy" --vus "$vus" --rep "$rep" \
    --start "$start" --end "$end" --qty "$QTY" --mode "$MODE" --pool "$POOL" --raw "$OUT/raw" >> "$OUT/runs.jsonl"
  echo "$(date +%H:%M:%S) $id done ($(python3 -c "print(round($end-$start,1))")s)"
}

echo "== $EXP  qty=$QTY mode=$MODE iterations=$ITERATIONS duration=$DURATION users=$USERS levels=[$LEVELS] strats=[$STRATS] reps=$REPS pool=$POOL tag=$TAG"
# 워밍업: 전략별 1회(200 VU), rep=warmup 으로 기록(리포트에서 제외)
if [ "${WARMUP:-1}" = 1 ]; then for s in $STRATS; do one_run "$s" 200 warmup; done; fi
for vus in $LEVELS; do
  for rep in $(seq 1 "$REPS"); do
    # 실행 순서 효과 상쇄: 반복마다 전략 순서를 회전
    arr=($STRATS); n=${#arr[@]}; rot=$(( (rep-1) % n ))
    for i in $(seq 0 $((n-1))); do one_run "${arr[$(( (i+rot) % n ))]}" "$vus" "$rep"; done
  done
done
echo "== $EXP finished"
