CREATE TABLE coupon (
  id              BIGINT       NOT NULL PRIMARY KEY,
  name            VARCHAR(100) NOT NULL,
  total_quantity  INT          NOT NULL,
  issued_quantity INT          NOT NULL DEFAULT 0,
  version         BIGINT       NOT NULL DEFAULT 0
) ENGINE=InnoDB;

CREATE TABLE coupon_issue (
  id        BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
  coupon_id BIGINT      NOT NULL,
  user_id   BIGINT      NOT NULL,
  issued_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uk_coupon_user (coupon_id, user_id)
) ENGINE=InnoDB;

INSERT INTO coupon (id, name, total_quantity) VALUES (1, 'lab-coupon', 100);

-- Prometheus mysqld-exporter 계정
CREATE USER 'exporter'@'%' IDENTIFIED BY 'exporter' WITH MAX_USER_CONNECTIONS 3;
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'exporter'@'%';
