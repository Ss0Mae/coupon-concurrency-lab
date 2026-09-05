package com.seongmin.coupon;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DeadlockLoserDataAccessException;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 네 가지 발급 전략을 한 곳에서 SQL 수준으로 드러낸다.
 * 모든 전략은 "coupon 1건 읽기/갱신 + coupon_issue 1건 INSERT" 한 트랜잭션이며,
 * 중복 발급은 coupon_issue(coupon_id, user_id) UNIQUE 제약으로 막는다.
 */
@Service
public class CouponIssueService {

	private static final String SELECT = "SELECT issued_quantity, total_quantity, version FROM coupon WHERE id = ?";
	private static final String SELECT_FOR_UPDATE = SELECT + " FOR UPDATE";
	private static final String INSERT_ISSUE = "INSERT INTO coupon_issue (coupon_id, user_id) VALUES (?, ?)";

	private final JdbcTemplate jdbc;
	private final TransactionTemplate tx;
	private final MeterRegistry registry;
	private final int maxRetries;

	public CouponIssueService(JdbcTemplate jdbc, PlatformTransactionManager txm, MeterRegistry registry,
			@Value("${coupon.optimistic.max-retries}") int maxRetries) {
		this.jdbc = jdbc;
		this.tx = new TransactionTemplate(txm);
		this.registry = registry;
		this.maxRetries = maxRetries;
	}

	public IssueResult issue(Strategy strategy, long couponId, long userId) {
		IssueResult result = switch (strategy) {
			case NO_LOCK -> noLock(couponId, userId);
			case PESSIMISTIC -> pessimistic(couponId, userId);
			case OPTIMISTIC -> optimistic(couponId, userId);
			case CONDITIONAL -> conditional(couponId, userId);
		};
		count("coupon_issue_total", strategy, "result", result.name());
		return result;
	}

	/** 1) 락 없음: 읽고 → 검사 → 절대값으로 UPDATE (JPA 더티체킹과 동일한 lost update 구조). */
	private IssueResult noLock(long couponId, long userId) {
		return tx.execute(st -> {
			Row c = read(SELECT, couponId);
			if (c.issued() >= c.total()) return IssueResult.SOLD_OUT;
			if (!insertIssue(couponId, userId)) { st.setRollbackOnly(); return IssueResult.DUPLICATE; }
			jdbc.update("UPDATE coupon SET issued_quantity = ? WHERE id = ?", c.issued() + 1, couponId);
			return IssueResult.ISSUED;
		});
	}

	/** 2) 비관적 락: SELECT ... FOR UPDATE 로 행을 잠근 뒤 검사·INSERT·UPDATE. 락은 커밋까지 유지. */
	private IssueResult pessimistic(long couponId, long userId) {
		return tx.execute(st -> {
			Row c = read(SELECT_FOR_UPDATE, couponId);
			if (c.issued() >= c.total()) { st.setRollbackOnly(); return IssueResult.SOLD_OUT; }
			if (!insertIssue(couponId, userId)) { st.setRollbackOnly(); return IssueResult.DUPLICATE; }
			jdbc.update("UPDATE coupon SET issued_quantity = issued_quantity + 1 WHERE id = ?", couponId);
			return IssueResult.ISSUED;
		});
	}

	/** 3) 낙관적 락: version 비교 UPDATE. 0행이면 충돌 → 새 트랜잭션으로 재시도(최대 maxRetries). */
	private IssueResult optimistic(long couponId, long userId) {
		for (int attempt = 0; ; attempt++) {
			IssueResult r = tx.execute(st -> {
				Row c = read(SELECT, couponId);
				if (c.issued() >= c.total()) return IssueResult.SOLD_OUT;
				if (!insertIssue(couponId, userId)) { st.setRollbackOnly(); return IssueResult.DUPLICATE; }
				int updated = jdbc.update(
						"UPDATE coupon SET issued_quantity = ?, version = version + 1 WHERE id = ? AND version = ?",
						c.issued() + 1, couponId, c.version());
				if (updated == 0) { st.setRollbackOnly(); return null; } // 충돌
				return IssueResult.ISSUED;
			});
			if (r != null) return r;
			count("coupon_optimistic_conflict_total", Strategy.OPTIMISTIC);
			if (attempt >= maxRetries) return IssueResult.RETRY_EXHAUSTED;
			count("coupon_retry_total", Strategy.OPTIMISTIC);
		}
	}

	/**
	 * 4) 조건부 UPDATE: 재고 검사와 증가를 한 문장(WHERE issued < total)으로 원자화.
	 * 잠금 없는 선조회로 품절을 빠르게 걸러 핫로우에 UPDATE 락을 걸지 않는다(REPEATABLE READ에서
	 * 조건 불일치 행도 커밋까지 잠기므로 중요). INSERT를 먼저 하고 UPDATE를 마지막에 두어
	 * 핫로우 락 보유 시간을 "UPDATE~COMMIT" 구간으로 최소화한다.
	 */
	private IssueResult conditional(long couponId, long userId) {
		return tx.execute(st -> {
			Row c = read(SELECT, couponId);
			if (c.issued() >= c.total()) return IssueResult.SOLD_OUT;
			if (!insertIssue(couponId, userId)) { st.setRollbackOnly(); return IssueResult.DUPLICATE; }
			int updated = jdbc.update(
					"UPDATE coupon SET issued_quantity = issued_quantity + 1 WHERE id = ? AND issued_quantity < total_quantity",
					couponId);
			if (updated == 0) { st.setRollbackOnly(); return IssueResult.SOLD_OUT; }
			return IssueResult.ISSUED;
		});
	}

	private record Row(int issued, int total, long version) {}

	private Row read(String sql, long couponId) {
		return jdbc.queryForObject(sql, (rs, i) -> new Row(rs.getInt(1), rs.getInt(2), rs.getLong(3)), couponId);
	}

	/** @return false = 이미 발급된 사용자(UNIQUE 위반) */
	private boolean insertIssue(long couponId, long userId) {
		try {
			jdbc.update(INSERT_ISSUE, couponId, userId);
			return true;
		} catch (DuplicateKeyException e) {
			return false;
		}
	}

	public void countDeadlock(Strategy s) {
		count("coupon_deadlock_total", s);
	}

	private void count(String name, Strategy s, String... extraTags) {
		String[] tags = new String[2 + extraTags.length];
		tags[0] = "strategy"; tags[1] = s.name();
		System.arraycopy(extraTags, 0, tags, 2, extraTags.length);
		Counter.builder(name).tags(tags).register(registry).increment();
	}
}
