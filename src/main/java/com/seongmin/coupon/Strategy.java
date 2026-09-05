package com.seongmin.coupon;

/** 쿠폰 발급 동시성 제어 방식. URL 경로 세그먼트(소문자, '-' 구분)로 선택한다. */
public enum Strategy {
	NO_LOCK, PESSIMISTIC, OPTIMISTIC, CONDITIONAL;

	public static Strategy fromPath(String s) {
		return valueOf(s.toUpperCase().replace('-', '_'));
	}
}
