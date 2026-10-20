\copy chain FROM '/data/chain.csv' WITH (FORMAT csv, HEADER true)
\copy store FROM '/data/store.csv' WITH (FORMAT csv, HEADER true)
\copy daily_store_metric FROM '/data/daily_store_metric.csv' WITH (FORMAT csv, HEADER true)
ANALYZE chain;
ANALYZE store;
ANALYZE daily_store_metric;
