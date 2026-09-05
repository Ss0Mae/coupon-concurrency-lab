#!/usr/bin/env bash
# 전체 실험 일괄 실행. 약 1시간 소요. 로그: results/all.log
set -uo pipefail
cd "$(dirname "$0")/.."
ulimit -n 10240
mq() { mysql -h127.0.0.1 -P3306 -uroot -proot -Dcoupon "$@" 2> >(grep -v "Using a password" >&2); }
echo "== all.sh start $(date)"
bench/app.sh stop; HIKARI_POOL_SIZE=20 bench/app.sh start
bench/run.sh coherence
bench/run.sh duplicate
bench/run.sh sustained
bench/run.sh soldout
# HikariCP 풀 크기 실험: 앱 재기동으로 풀 크기 변경
for pool in 10 20 50; do
  bench/app.sh stop; HIKARI_POOL_SIZE=$pool bench/app.sh start
  HIKARI_POOL_SIZE=$pool TAG=pool$pool bench/run.sh poolsize
done
bench/app.sh stop; HIKARI_POOL_SIZE=20 bench/app.sh start
# UNIQUE 제약이 없을 때 중복 발급 재현
mq -e "ALTER TABLE coupon_issue DROP INDEX uk_coupon_user"
TAG=nounique bench/run.sh nounique
mq -e "TRUNCATE coupon_issue; ALTER TABLE coupon_issue ADD UNIQUE KEY uk_coupon_user (coupon_id, user_id)"
echo "== all.sh end $(date)"
