#!/usr/bin/env bash
# 2차 배치: 포트 소진으로 실패한 실험 재실행 (coherence 1000VU 재측정, duplicate, sustained, soldout)
set -uo pipefail
cd "$(dirname "$0")/.."
ulimit -n 10240
echo "== all2.sh start $(date)"
bench/app.sh stop; HIKARI_POOL_SIZE=20 bench/app.sh start
LEVELS=1000 bench/run.sh coherence
WARMUP=0 bench/run.sh duplicate
WARMUP=0 bench/run.sh sustained
WARMUP=0 bench/run.sh soldout
echo "== all2.sh end $(date)"
