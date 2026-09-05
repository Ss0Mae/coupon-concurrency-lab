#!/usr/bin/env bash
# 3차 배치: 재고가 남아 있는 상태에서의 중복 요청 차단 검증 (UNIQUE 있음/없음)
set -uo pipefail
cd "$(dirname "$0")/.."
ulimit -n 10240
mq() { mysql -h127.0.0.1 -P3306 -uroot -proot -Dcoupon "$@" 2> >(grep -v "Using a password" >&2); }
echo "== all3.sh start $(date)"
WARMUP=0 bench/run.sh dupopen
mq -e "ALTER TABLE coupon_issue DROP INDEX uk_coupon_user"
WARMUP=0 TAG=nounique bench/run.sh nouniqueopen
mq -e "TRUNCATE coupon_issue; ALTER TABLE coupon_issue ADD UNIQUE KEY uk_coupon_user (coupon_id, user_id)"
mq -e "SHOW INDEX FROM coupon_issue WHERE Key_name='uk_coupon_user'" | head -2
echo "== all3.sh end $(date)"
