package com.seongmin.coupon;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.bind.annotation.*;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;

/**
 * 웹 UI(web/)용 라이브 실행기. 자기 자신의 발급 API를 HTTP 로 N건 호출해 k6 와 같은 경로(Tomcat → 서비스 → MySQL)를 지나게 한다.
 * 측정 도구가 아니라 시연용이며, 정식 수치는 bench/ 의 k6 실측을 따른다.
 */
@RestController
@RequestMapping("/api/demo")
public class DemoController {

	private final JdbcTemplate jdbc;
	private final TransactionTemplate tx;
	private final int port;
	private final HttpClient http = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build();

	public DemoController(JdbcTemplate jdbc, PlatformTransactionManager txm, @Value("${server.port}") int port) {
		this.jdbc = jdbc;
		this.tx = new TransactionTemplate(txm);
		this.port = port;
	}

	public record RunRequest(String strategy, Long couponId, Integer totalQuantity, Integer users, Integer requests, Integer concurrency) {}

	@GetMapping("/state")
	public Map<String, Object> state(@RequestParam(defaultValue = "1") long couponId) {
		return dbState(couponId);
	}

	@PostMapping("/reset")
	public Map<String, Object> reset(@RequestBody RunRequest req) {
		long couponId = req.couponId() == null ? 1 : req.couponId();
		resetDb(couponId, clamp(req.totalQuantity(), 100, 0, 10_000_000));
		return dbState(couponId);
	}

	@PostMapping("/run")
	public Map<String, Object> run(@RequestBody RunRequest req) throws InterruptedException {
		Strategy s = Strategy.fromPath(req.strategy());
		long couponId = req.couponId() == null ? 1 : req.couponId();
		int qty = clamp(req.totalQuantity(), 100, 0, 10_000_000);
		int users = clamp(req.users(), 1000, 1, 1_000_000);
		int n = clamp(req.requests(), 1000, 1, 20_000);
		int c = clamp(req.concurrency(), 200, 1, 1_000);
		resetDb(couponId, qty);

		URI uri = URI.create("http://127.0.0.1:" + port + "/api/coupons/" + couponId + "/issue/" + s.name().toLowerCase().replace('_', '-'));
		int[] status = new int[n];
		long[] lat = new long[n];
		Semaphore gate = new Semaphore(c); // 동시성 = 동시에 열려 있는 요청 수 (k6 VU 와 같은 의미)
		long t0 = System.nanoTime();
		try (var pool = Executors.newVirtualThreadPerTaskExecutor()) {
			for (int i = 0; i < n; i++) {
				final int idx = i;
				final long userId = 1 + (i % users);
				pool.submit(() -> {
					gate.acquire();
					try {
						HttpRequest rq = HttpRequest.newBuilder(uri).header("Content-Type", "application/json")
								.POST(HttpRequest.BodyPublishers.ofString("{\"userId\":" + userId + "}")).build();
						long s0 = System.nanoTime();
						try {
							status[idx] = http.send(rq, HttpResponse.BodyHandlers.discarding()).statusCode();
						} catch (Exception e) {
							status[idx] = 599; // 연결 실패도 서버 오류로 집계
						}
						lat[idx] = System.nanoTime() - s0;
					} finally {
						gate.release();
					}
					return null;
				});
			}
		} // close() 는 모든 작업 완료까지 대기
		double elapsedMs = (System.nanoTime() - t0) / 1e6;

		int issued = 0, soldOut = 0, dup = 0, err = 0;
		for (int st : status) {
			if (st == 200) issued++;
			else if (st == 410) soldOut++;
			else if (st == 409) dup++;
			else err++;
		}
		Arrays.sort(lat);
		Map<String, Object> db = dbState(couponId);
		int dbIssues = (Integer) db.get("issues"), distinct = (Integer) db.get("distinct_users");
		int issuedQty = (Integer) db.get("issued_quantity"), total = (Integer) db.get("total_quantity");
		int overIssue = Math.max(0, dbIssues - total), dupIssue = dbIssues - distinct;
		int respDbMismatch = issued - dbIssues, stockMismatch = dbIssues - issuedQty;

		Map<String, Object> out = new LinkedHashMap<>();
		out.put("strategy", s.name());
		out.put("params", Map.of("couponId", couponId, "totalQuantity", qty, "users", users, "requests", n, "concurrency", c));
		out.put("elapsed_ms", round(elapsedMs, 1));
		out.put("tps", round(n / elapsedMs * 1000, 1));
		out.put("success_tps", round(issued / elapsedMs * 1000, 1));
		out.put("counts", Map.of("issued", issued, "sold_out", soldOut, "duplicate", dup, "server_error", err));
		out.put("latency", Map.of("avg", round(Arrays.stream(lat).average().orElse(0) / 1e6, 1), "p50", pct(lat, 0.5), "p95", pct(lat, 0.95), "p99", pct(lat, 0.99), "max", pct(lat, 1)));
		out.put("db", db);
		Map<String, Object> integrity = new LinkedHashMap<>();
		integrity.put("over_issue", overIssue);
		integrity.put("dup_issue", dupIssue);
		integrity.put("resp_db_mismatch", respDbMismatch);
		integrity.put("stock_mismatch", stockMismatch);
		integrity.put("ok", overIssue == 0 && dupIssue == 0 && respDbMismatch == 0 && stockMismatch == 0);
		out.put("integrity", integrity);
		return out;
	}

	private void resetDb(long couponId, int qty) {
		// bench/run.sh 와 같이 TRUNCATE 로 비운다(DDL, 즉시 커밋). DELETE 로 지우면 삭제 표시된 UNIQUE 레코드가 purge 전까지 남아
		// 같은 (coupon_id, user_id) 를 다시 INSERT 할 때 갭 락이 걸리고, 핫로우 UPDATE 와 맞물려 데드락이 1건 관측됐다.
		jdbc.execute("TRUNCATE TABLE coupon_issue");
		tx.executeWithoutResult(st -> // Hikari auto-commit=false 이므로 트랜잭션 밖의 DML 은 반환 시 롤백된다
			jdbc.update("UPDATE coupon SET total_quantity = ?, issued_quantity = 0, version = 0 WHERE id = ?", qty, couponId));
	}

	private Map<String, Object> dbState(long couponId) {
		Map<String, Object> m = new LinkedHashMap<>();
		jdbc.query("SELECT issued_quantity, total_quantity FROM coupon WHERE id = ?", rs -> {
			m.put("issued_quantity", rs.getInt(1));
			m.put("total_quantity", rs.getInt(2));
		}, couponId);
		jdbc.query("SELECT COUNT(*), COUNT(DISTINCT user_id) FROM coupon_issue WHERE coupon_id = ?", rs -> {
			m.put("issues", rs.getInt(1));
			m.put("distinct_users", rs.getInt(2));
		}, couponId);
		return m;
	}

	private static int clamp(Integer v, int def, int lo, int hi) {
		return v == null ? def : Math.max(lo, Math.min(hi, v));
	}

	private static double pct(long[] sorted, double q) {
		if (sorted.length == 0) return 0;
		int i = Math.min(sorted.length - 1, Math.max(0, (int) Math.ceil(q * sorted.length) - 1));
		return round(sorted[i] / 1e6, 1);
	}

	private static double round(double v, int d) {
		double f = Math.pow(10, d);
		return Math.round(v * f) / f;
	}
}
