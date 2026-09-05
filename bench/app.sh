#!/usr/bin/env bash
# 애플리케이션 기동/종료. 모든 실험에서 동일한 JVM 옵션을 사용한다.
set -euo pipefail
cd "$(dirname "$0")/.."
JVM_OPTS="-Xms1g -Xmx1g -XX:+UseG1GC -XX:+AlwaysPreTouch"
JAR=$(ls build/libs/coupon-concurrency-lab-*.jar | head -1)
case "${1:-start}" in
  start)
    export HIKARI_POOL_SIZE=${HIKARI_POOL_SIZE:-20} TOMCAT_MAX_THREADS=${TOMCAT_MAX_THREADS:-200} OPTIMISTIC_MAX_RETRIES=${OPTIMISTIC_MAX_RETRIES:-20}
    mkdir -p results
    nohup java $JVM_OPTS -jar "$JAR" > results/app.log 2>&1 &
    echo $! > results/app.pid
    for i in $(seq 1 60); do
      curl -sf localhost:8080/actuator/health >/dev/null 2>&1 && { echo "app up (pid $(cat results/app.pid), pool=$HIKARI_POOL_SIZE, tomcat=$TOMCAT_MAX_THREADS, retries=$OPTIMISTIC_MAX_RETRIES)"; exit 0; }
      sleep 1
    done
    echo "app failed to start"; tail -30 results/app.log; exit 1;;
  stop)
    [ -f results/app.pid ] && kill "$(cat results/app.pid)" 2>/dev/null && rm -f results/app.pid && echo "app stopped" || echo "no app";
    sleep 1;;
esac
