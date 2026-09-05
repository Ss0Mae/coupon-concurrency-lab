package com.seongmin.coupon;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.dao.PessimisticLockingFailureException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.sql.SQLException;
import java.util.Map;

@RestController
public class CouponController {

	private final CouponIssueService service;
	private final MeterRegistry registry;

	public CouponController(CouponIssueService service, MeterRegistry registry) {
		this.service = service;
		this.registry = registry;
	}

	public record IssueRequest(long userId) {}

	@PostMapping("/api/coupons/{couponId}/issue/{strategy}")
	public ResponseEntity<Map<String, Object>> issue(@PathVariable long couponId, @PathVariable String strategy,
			@RequestBody IssueRequest req) {
		Strategy s = Strategy.fromPath(strategy);
		try {
			IssueResult r = service.issue(s, couponId, req.userId());
			return ResponseEntity.status(r.httpStatus).body(Map.of("result", r.name(), "strategy", s.name()));
		} catch (PessimisticLockingFailureException e) {
			// Spring 6+ 기본 번역기(SQLExceptionSubclassTranslator)는 MySQL 데드락(1213, SQLState 40001)을
			// DeadlockLoserDataAccessException 이 아니라 CannotAcquireLockException 으로 던지므로 벤더 코드로 구분한다.
			if (e.getMostSpecificCause() instanceof SQLException se && se.getErrorCode() == 1213) {
				service.countDeadlock(s);
				return error(s, "DEADLOCK");
			}
			return error(s, e.getClass().getSimpleName());
		} catch (RuntimeException e) {
			return error(s, e.getClass().getSimpleName());
		}
	}

	private ResponseEntity<Map<String, Object>> error(Strategy s, String kind) {
		Counter.builder("coupon_error_total").tags("strategy", s.name(), "kind", kind).register(registry).increment();
		return ResponseEntity.status(500).body(Map.of("result", "ERROR", "kind", kind, "strategy", s.name()));
	}
}
