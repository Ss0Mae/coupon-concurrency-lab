# 메트릭·수집 설정·Grafana 패널

## 1. 수집 구조

```text
k6 (호스트) ──HTTP──▶ Spring Boot 앱 (호스트, :8080) ──JDBC──▶ MySQL 8.0 (Docker, :3306)
                          │ /actuator/prometheus                     │
                          ▼                                          ▼ mysqld-exporter (:9104)
                    Prometheus (Docker, :9090, scrape 1s) ◀──────────┘
                          │
                          ▼
                    Grafana (Docker, :3000, 대시보드 "Coupon Concurrency Lab")
```

- 요청 단위 지표(TPS, p50/p95/p99, 응답 분류)는 **k6 요약 JSON**이 1차 출처다. 시간축 그래프는 Prometheus.
- DB 진실값(발급 건수, issued_quantity, 행 잠금 누적, SQL 다이제스트)은 `bench/run.sh`가 실행 전후에 MySQL에서 직접 읽는다.
- 설정 파일: `docker/prometheus/prometheus.yml`, `docker/grafana/provisioning/*`, `docker/grafana/dashboards/coupon-lab.json`.

## 2. 메트릭 이름

### 애플리케이션 (Micrometer → `/actuator/prometheus`)

| 지표 | 메트릭 | 비고 |
|---|---|---|
| 요청 수·응답시간 히스토그램 | `http_server_requests_seconds_count / _sum / _bucket{uri="/api/coupons/{couponId}/issue/{strategy}",status}` | `percentiles-histogram` 활성화 → `histogram_quantile` 로 p95/p99 |
| 발급 결과 분류 | `coupon_issue_total{strategy,result=ISSUED\|SOLD_OUT\|DUPLICATE\|RETRY_EXHAUSTED}` | 서비스에서 증가 |
| 낙관적 락 충돌 | `coupon_optimistic_conflict_total{strategy}` | version 불일치로 0행 갱신 |
| 재시도 | `coupon_retry_total{strategy}` | 충돌 후 재시도 횟수 |
| 데드락(앱 감지) | `coupon_deadlock_total{strategy}` | `PessimisticLockingFailureException` 중 MySQL 오류 코드 1213. Spring 6+ 는 데드락을 `CannotAcquireLockException` 으로 번역하므로 클래스가 아니라 벤더 코드로 판별 |
| 서버 오류 | `coupon_error_total{strategy,kind}` | 500 응답 |
| 활성/유휴/대기 커넥션 | `hikaricp_connections_active`, `hikaricp_connections_idle`, `hikaricp_connections_pending` | 게이지 |
| 커넥션 획득 대기시간 | `hikaricp_connections_acquire_seconds_sum / _count / _max` | 평균 = sum/count 의 구간 증가분 |
| 커넥션 사용 시간 | `hikaricp_connections_usage_seconds_*` | |
| CPU | `process_cpu_usage`, `system_cpu_usage` | 0~1 |
| 메모리 | `jvm_memory_used_bytes{area="heap"}` | |

### MySQL (mysqld-exporter)

| 지표 | 메트릭 |
|---|---|
| 행 잠금 대기 누적 시간(ms) | `mysql_global_status_innodb_row_lock_time` |
| 행 잠금 대기 횟수 | `mysql_global_status_innodb_row_lock_waits` |
| 현재 행 잠금 대기 수 | `mysql_global_status_innodb_row_lock_current_waits` |
| 데드락 누적 | `mysql_info_schema_innodb_metrics_lock_lock_deadlocks_total` |
| 접속/실행 스레드 | `mysql_global_status_threads_connected`, `mysql_global_status_threads_running` |
| 명령 수 | `mysql_global_status_commands_total{command="select"\|"insert"\|"update"\|"commit"\|"rollback"}` |

### 실행 단위로 직접 읽는 값 (`bench/run.sh` → `results/<exp>/runs.jsonl`)

- `SHOW GLOBAL STATUS` 의 `Innodb_row_lock_waits`, `Innodb_row_lock_time`, `Innodb_row_lock_time_max`, `Com_*` 전후 차분
- `information_schema.INNODB_METRICS` 의 `lock_deadlocks`, `lock_timeouts` 전후 차분
- `performance_schema.events_statements_summary_by_digest` (실행 전 TRUNCATE): 문장별 실행 수, 평균/최대 실행시간, 잠금 시간
- 검증 쿼리: `COUNT(*)`, `COUNT(DISTINCT user_id)` (coupon_issue), `issued_quantity`, `total_quantity` (coupon)
- `docker stats` 1초 표본 → MySQL 컨테이너 CPU/메모리

## 3. Prometheus 수집 설정 (`docker/prometheus/prometheus.yml`)

```yaml
global:
  scrape_interval: 1s
scrape_configs:
  - job_name: coupon-app
    metrics_path: /actuator/prometheus
    static_configs: [{ targets: ["host.docker.internal:8080"] }]
  - job_name: mysql
    static_configs: [{ targets: ["mysqld-exporter:9104"] }]
```

`spring-boot-starter-actuator` + `micrometer-registry-prometheus`, `management.endpoints.web.exposure.include=prometheus`,
`management.metrics.distribution.percentiles-histogram.http.server.requests=true`.

## 4. Grafana 패널 (`docker/grafana/dashboards/coupon-lab.json`, 자동 프로비저닝)

| 패널 | PromQL |
|---|---|
| 전체 TPS (전략별) | `sum by (uri) (rate(http_server_requests_seconds_count{uri=~"/api/coupons.*"}[5s]))` |
| 성공 발급 TPS | `sum by (strategy) (rate(coupon_issue_total{result="ISSUED"}[5s]))` |
| p95 / p99 | `histogram_quantile(0.95, sum by (le, uri) (rate(http_server_requests_seconds_bucket{uri=~"/api/coupons.*"}[5s])))` |
| HikariCP 활성/유휴/대기 | `hikaricp_connections_active`, `hikaricp_connections_idle`, `hikaricp_connections_pending` |
| 커넥션 획득 대기시간 | `rate(hikaricp_connections_acquire_seconds_sum[5s]) / rate(hikaricp_connections_acquire_seconds_count[5s])`, `hikaricp_connections_acquire_seconds_max` |
| 행 잠금 대기시간 (ms/s) | `rate(mysql_global_status_innodb_row_lock_time[5s])`, `rate(mysql_global_status_innodb_row_lock_waits[5s])` |
| 현재 잠금 대기 / 데드락 | `mysql_global_status_innodb_row_lock_current_waits`, `mysql_info_schema_innodb_metrics_lock_lock_deadlocks_total` |
| 응답 결과 비율 (파이) | `sum by (result) (increase(coupon_issue_total[$__range]))`, `sum(increase(coupon_error_total[$__range]))` |
| 낙관적 락 충돌/재시도 | `rate(coupon_optimistic_conflict_total[5s])`, `rate(coupon_retry_total[5s])` |
| CPU | `process_cpu_usage`, `system_cpu_usage` |
| JVM 힙 | `sum(jvm_memory_used_bytes{area="heap"})`, `sum(jvm_memory_max_bytes{area="heap"})` |
| MySQL 스레드 | `mysql_global_status_threads_connected`, `mysql_global_status_threads_running` |
| SQL 종류별 초당 실행 수 | `rate(mysql_global_status_commands_total{command=~"select\|insert\|update\|commit\|rollback"}[5s])` |

구현 방식별 비교 막대그래프, 동시 사용자별 추이, 개선 전후 정합성처럼 **실행 간 집계**가 필요한 그래프는
Prometheus 시계열이 아니라 `results/*/runs.jsonl` 을 `bench/report.py` 로 집계해 `docs/charts/*.png` 로 생성한다.

## 5. 한계

- Prometheus 스크레이프가 1초이므로 1초 안에 끝나는 실행(coherence 저 VU 구간)은 시간축 지표 표본이 0~1개다. 그런 실행의 커넥션 대기·CPU 값은 신뢰하지 않는다.
- `hikaricp_connections_acquire_seconds_max` 는 Micrometer 의 감쇠 최대값(최근 창)이라 실행 종료 직후 값이 "그 실행의 최대"에 가깝지만 엄밀히 같지는 않다.
- `Innodb_row_lock_time_max` 는 서버 기동 이후 전역 최대값이라 실행별 값이 아니다(실행별 평균은 전후 차분으로 계산).
