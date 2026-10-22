UPDATE report_threshold SET annul_share_max_pct = 2 WHERE id = 1;

CREATE OR REPLACE VIEW v_chain_outlier AS
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
      THEN 'доля аннуляций выше ' || trim(to_char(t.annul_share_max_pct, 'FM990.0')) || '%' END
  ) AS outlier_reason
FROM agg a
CROSS JOIN report_threshold t
WHERE a.sco_share_pct < t.sco_share_min_pct
   OR a.annul_share_pct > t.annul_share_max_pct;

CREATE OR REPLACE VIEW v_store_outlier AS
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
      THEN 'доля аннуляций выше ' || trim(to_char(t.annul_share_max_pct, 'FM990.0')) || '%' END
  ) AS outlier_reason
FROM agg a
CROSS JOIN report_threshold t
WHERE a.sco_share_pct < t.sco_share_min_pct
   OR a.annul_share_pct > t.annul_share_max_pct;
