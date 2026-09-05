package com.seongmin.coupon;

public enum IssueResult {
	ISSUED(200), SOLD_OUT(410), DUPLICATE(409), RETRY_EXHAUSTED(503);

	public final int httpStatus;

	IssueResult(int httpStatus) {
		this.httpStatus = httpStatus;
	}
}
