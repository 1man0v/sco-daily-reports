-- Суточные агрегаты КСО и представления для трёх отчётов.
-- Доли за период считаются как сумма числителей / сумма знаменателей.
-- В суммы входят только магазины с has_sco = true.

CREATE TABLE chain (
  id text PRIMARY KEY,
  name text NOT NULL UNIQUE
);

CREATE TABLE store (
  id text PRIMARY KEY,
  chain_id text NOT NULL REFERENCES chain (id),
  name text NOT NULL,
  has_sco boolean NOT NULL,
  sco_registers integer NOT NULL CHECK (sco_registers >= 0),
  pos_registers integer NOT NULL CHECK (pos_registers >= 0),
  CHECK ((has_sco AND sco_registers > 0) OR (NOT has_sco AND sco_registers = 0))
);

CREATE TABLE daily_store_metric (
  store_id text NOT NULL REFERENCES store (id),
  report_date date NOT NULL,
  sco_receipts integer NOT NULL CHECK (sco_receipts >= 0),          -- SCO-001
  pos_receipts integer NOT NULL CHECK (pos_receipts >= 0),          -- SCO-017
  sco_annulled integer NOT NULL CHECK (sco_annulled >= 0),          -- SCO-005
  pos_potential integer NOT NULL CHECK (pos_potential >= 0),        -- SCO-022
  sco_items_p95 numeric NOT NULL CHECK (sco_items_p95 >= 0),        -- SCO-002
  sco_avg_duration_sec numeric NOT NULL CHECK (sco_avg_duration_sec >= 0), -- SCO-004
  sco_avg_annul_sec numeric NOT NULL CHECK (sco_avg_annul_sec >= 0),       -- SCO-006
  PRIMARY KEY (store_id, report_date),
  CHECK (sco_annulled <= sco_receipts),
  CHECK (pos_potential <= pos_receipts)
);

CREATE INDEX daily_store_metric_date_idx ON daily_store_metric (report_date);

-- 30% — норматив доли чеков КСО из требований продукта.
-- 3% и 40% — стартовые значения примера для аннуляций и перетока, не норматив.
CREATE TABLE report_threshold (
  id integer PRIMARY KEY CHECK (id = 1),
  sco_share_min_pct numeric NOT NULL,
  annul_share_max_pct numeric NOT NULL,
  transfer_share_max_pct numeric NOT NULL
);

INSERT INTO report_threshold (id, sco_share_min_pct, annul_share_max_pct, transfer_share_max_pct)
VALUES (1, 30, 3, 40);

CREATE VIEW v_daily_fact AS
SELECT
  m.report_date,
  c.id AS chain_id,
  c.name AS chain_name,
  s.id AS store_id,
  s.name AS store_name,
  s.sco_registers,
  s.pos_registers,
  cc.stores_with_sco,
  cc.stores_without_sco,
  m.sco_receipts,
  m.pos_receipts,
  m.sco_annulled,
  m.pos_potential,
  m.sco_items_p95,
  m.sco_avg_duration_sec,
  m.sco_avg_annul_sec
FROM daily_store_metric m
JOIN store s ON s.id = m.store_id AND s.has_sco
JOIN chain c ON c.id = s.chain_id
JOIN (
  SELECT
    chain_id,
    COUNT(*) FILTER (WHERE has_sco) AS stores_with_sco,
    COUNT(*) FILTER (WHERE NOT has_sco) AS stores_without_sco
  FROM store
  GROUP BY chain_id
) cc ON cc.chain_id = c.id;

-- Аутсайдер определяется по доле за весь период, поэтому период собран внутри представления.
-- Граница периода — последняя дата в данных, а не календарное «сегодня».
CREATE VIEW v_chain_outlier AS
WITH anchor AS (
  SELECT MAX(report_date) AS last_day FROM daily_store_metric
),
bounds AS (
  SELECT '7 дней'::text AS period_name, (last_day - 6) AS date_from, (last_day + 1) AS date_to FROM anchor
  UNION ALL
  SELECT '30 дней', (last_day - 29), (last_day + 1) FROM anchor
  UNION ALL
  SELECT '60 дней', (last_day - 59), (last_day + 1) FROM anchor
),
agg AS (
  SELECT
    b.period_name,
    b.date_from,
    (b.date_to - 1) AS date_to_inclusive,
    c.name AS chain_name,
    MAX(cc.stores_with_sco) AS stores_with_sco,
    MAX(cc.stores_without_sco) AS stores_without_sco,
    SUM(m.sco_receipts)::bigint AS sco_receipts,
    SUM(m.pos_receipts)::bigint AS pos_receipts,
    SUM(m.sco_annulled)::bigint AS sco_annulled,
    SUM(m.pos_potential)::bigint AS pos_potential,
    SUM(m.sco_receipts) * 100.0 / NULLIF(SUM(m.sco_receipts) + SUM(m.pos_receipts), 0) AS sco_share_pct,
    SUM(m.sco_annulled) * 100.0 / NULLIF(SUM(m.sco_receipts), 0) AS annul_share_pct,
    SUM(m.pos_potential) * 100.0 / NULLIF(SUM(m.pos_receipts), 0) AS transfer_share_pct
  FROM bounds b
  JOIN daily_store_metric m ON m.report_date >= b.date_from AND m.report_date < b.date_to
  JOIN store s ON s.id = m.store_id AND s.has_sco
  JOIN chain c ON c.id = s.chain_id
  JOIN (
    SELECT
      chain_id,
      COUNT(*) FILTER (WHERE has_sco) AS stores_with_sco,
      COUNT(*) FILTER (WHERE NOT has_sco) AS stores_without_sco
    FROM store
    GROUP BY chain_id
  ) cc ON cc.chain_id = c.id
  GROUP BY b.period_name, b.date_from, b.date_to, c.name
)
SELECT
  a.period_name,
  a.date_from,
  a.date_to_inclusive,
  a.chain_name,
  a.stores_with_sco,
  a.stores_without_sco,
  a.sco_receipts,
  a.pos_receipts,
  a.sco_annulled,
  a.pos_potential,
  ROUND(a.sco_share_pct, 1) AS sco_share_pct,
  ROUND(a.annul_share_pct, 1) AS annul_share_pct,
  ROUND(a.transfer_share_pct, 1) AS transfer_share_pct,
  CASE WHEN a.sco_share_pct < t.sco_share_min_pct THEN 'да' ELSE 'нет' END AS low_sco_share,
  CASE WHEN a.annul_share_pct > t.annul_share_max_pct THEN 'да' ELSE 'нет' END AS high_annul_share,
  CASE WHEN a.transfer_share_pct > t.transfer_share_max_pct THEN 'да' ELSE 'нет' END AS high_transfer_share,
  concat_ws('; ',
    CASE WHEN a.sco_share_pct < t.sco_share_min_pct
      THEN 'доля чеков КСО ниже ' || trim(to_char(t.sco_share_min_pct, 'FM990.0')) || '%' END,
    CASE WHEN a.annul_share_pct > t.annul_share_max_pct
      THEN 'доля аннуляций выше ' || trim(to_char(t.annul_share_max_pct, 'FM990.0')) || '%' END,
    CASE WHEN a.transfer_share_pct > t.transfer_share_max_pct
      THEN 'доля перетока выше ' || trim(to_char(t.transfer_share_max_pct, 'FM990.0')) || '%' END
  ) AS outlier_reason
FROM agg a
CROSS JOIN report_threshold t
WHERE a.sco_share_pct < t.sco_share_min_pct
   OR a.annul_share_pct > t.annul_share_max_pct
   OR a.transfer_share_pct > t.transfer_share_max_pct;

CREATE VIEW v_store_outlier AS
WITH anchor AS (
  SELECT MAX(report_date) AS last_day FROM daily_store_metric
),
bounds AS (
  SELECT '7 дней'::text AS period_name, (last_day - 6) AS date_from, (last_day + 1) AS date_to FROM anchor
  UNION ALL
  SELECT '30 дней', (last_day - 29), (last_day + 1) FROM anchor
  UNION ALL
  SELECT '60 дней', (last_day - 59), (last_day + 1) FROM anchor
),
agg AS (
  SELECT
    b.period_name,
    c.name AS chain_name,
    s.name AS store_name,
    MAX(s.sco_registers) AS sco_registers,
    MAX(s.pos_registers) AS pos_registers,
    SUM(m.sco_receipts)::bigint AS sco_receipts,
    SUM(m.pos_receipts)::bigint AS pos_receipts,
    SUM(m.sco_annulled)::bigint AS sco_annulled,
    SUM(m.pos_potential)::bigint AS pos_potential,
    SUM(m.sco_receipts) * 100.0 / NULLIF(SUM(m.sco_receipts) + SUM(m.pos_receipts), 0) AS sco_share_pct,
    SUM(m.sco_annulled) * 100.0 / NULLIF(SUM(m.sco_receipts), 0) AS annul_share_pct,
    SUM(m.pos_potential) * 100.0 / NULLIF(SUM(m.pos_receipts), 0) AS transfer_share_pct,
    SUM(m.sco_items_p95 * m.sco_receipts) / NULLIF(SUM(m.sco_receipts), 0) AS sco_items_p95,
    SUM(m.sco_avg_duration_sec * m.sco_receipts) / NULLIF(SUM(m.sco_receipts), 0) AS sco_avg_duration_sec,
    SUM(m.sco_avg_annul_sec * m.sco_annulled) / NULLIF(SUM(m.sco_annulled), 0) AS sco_avg_annul_sec
  FROM bounds b
  JOIN daily_store_metric m ON m.report_date >= b.date_from AND m.report_date < b.date_to
  JOIN store s ON s.id = m.store_id AND s.has_sco
  JOIN chain c ON c.id = s.chain_id
  GROUP BY b.period_name, c.name, s.name
)
SELECT
  a.period_name,
  a.chain_name,
  a.store_name,
  a.sco_registers,
  a.pos_registers,
  a.sco_receipts,
  a.pos_receipts,
  a.sco_annulled,
  a.pos_potential,
  ROUND(a.sco_share_pct, 1) AS sco_share_pct,
  ROUND(a.annul_share_pct, 1) AS annul_share_pct,
  ROUND(a.transfer_share_pct, 1) AS transfer_share_pct,
  ROUND(a.sco_items_p95, 1) AS sco_items_p95,
  ROUND(a.sco_avg_duration_sec, 1) AS sco_avg_duration_sec,
  ROUND(a.sco_avg_annul_sec, 1) AS sco_avg_annul_sec,
  CASE WHEN a.sco_share_pct < t.sco_share_min_pct THEN 'да' ELSE 'нет' END AS low_sco_share,
  CASE WHEN a.annul_share_pct > t.annul_share_max_pct THEN 'да' ELSE 'нет' END AS high_annul_share,
  CASE WHEN a.transfer_share_pct > t.transfer_share_max_pct THEN 'да' ELSE 'нет' END AS high_transfer_share,
  concat_ws('; ',
    CASE WHEN a.sco_share_pct < t.sco_share_min_pct
      THEN 'доля чеков КСО ниже ' || trim(to_char(t.sco_share_min_pct, 'FM990.0')) || '%' END,
    CASE WHEN a.annul_share_pct > t.annul_share_max_pct
      THEN 'доля аннуляций выше ' || trim(to_char(t.annul_share_max_pct, 'FM990.0')) || '%' END,
    CASE WHEN a.transfer_share_pct > t.transfer_share_max_pct
      THEN 'доля перетока выше ' || trim(to_char(t.transfer_share_max_pct, 'FM990.0')) || '%' END
  ) AS outlier_reason
FROM agg a
CROSS JOIN report_threshold t
WHERE a.sco_share_pct < t.sco_share_min_pct
   OR a.annul_share_pct > t.annul_share_max_pct
   OR a.transfer_share_pct > t.transfer_share_max_pct;

CREATE VIEW v_threshold AS
SELECT
  sco_share_min_pct,
  annul_share_max_pct,
  transfer_share_max_pct
FROM report_threshold;
