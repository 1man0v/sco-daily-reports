ALTER TABLE chain ADD COLUMN IF NOT EXISTS country text;
ALTER TABLE chain ADD COLUMN IF NOT EXISTS region text;
ALTER TABLE chain ADD COLUMN IF NOT EXISTS store_format text;
CREATE INDEX IF NOT EXISTS store_chain_idx ON store (chain_id);

CREATE OR REPLACE VIEW v_daily_fact AS
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
  m.sco_avg_annul_sec,
  c.country,
  c.region,
  c.store_format,
  cc.stores_with_pos,
  cc.sco_registers_total,
  cc.pos_registers_total
FROM daily_store_metric m
JOIN store s ON s.id = m.store_id AND s.has_sco
JOIN chain c ON c.id = s.chain_id
JOIN (
  SELECT
    chain_id,
    COUNT(*) FILTER (WHERE has_sco) AS stores_with_sco,
    COUNT(*) FILTER (WHERE NOT has_sco) AS stores_without_sco,
    COUNT(*) FILTER (WHERE pos_registers > 0) AS stores_with_pos,
    COALESCE(SUM(sco_registers), 0) AS sco_registers_total,
    COALESCE(SUM(pos_registers), 0) AS pos_registers_total
  FROM store
  GROUP BY chain_id
) cc ON cc.chain_id = c.id;
