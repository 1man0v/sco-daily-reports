# Суточные отчёты КСО

Три отчёта Apache Superset по суточным агрегатам касс самообслуживания и POS. Это пример для просмотра на сервере, не HTML-прототип.

Откройте в браузере:

- клиенты: `http://<адрес-сервера>:8088/superset/dashboard/clients/`
- магазины клиента: `http://<адрес-сервера>:8088/superset/dashboard/stores/`
- аутсайдеры: `http://<адрес-сервера>:8088/superset/dashboard/outliers/`

Логин `admin`. Пароль лежит на сервере в файле `.env`, ключ `SUPERSET_ADMIN_PASSWORD`. В git пароля нет. После входа, если открылась стартовая страница Superset, перейдите по ссылке отчёта ещё раз.

Как применить схему и дашборды на своём Superset: [docs/apply.md](docs/apply.md).

Какое имя в отчёте какому коду требования, столбцу Postgres и метрике Superset соответствует: [docs/metrics.md](docs/metrics.md). В коде кассы и в JS этих имён ещё нет, таблица в том файле и есть договорённость для поставки.

## Что внутри

- Postgres хранит справочник сетей и магазинов и суточные метрики SCO-001, SCO-017, SCO-005, SCO-022, SCO-002, SCO-004, SCO-006. Столбцы и имена метрик Superset перечислены в [docs/metrics.md](docs/metrics.md).
- Superset только показывает эти данные. Формулы долей собраны в метриках датасета `v_daily_fact` и в представлениях `v_chain_outlier` и `v_store_outlier`.
- Демо-список — 150 сетей в `data/`. Свой файл кладут в те же столбцы. Каталог `data/live/` и книга клиентов в git не входят.

Пока список демо, в каждой сети часть магазинов может быть без КСО. Такие магазины видны в счётчике «Магазинов без КСО» и не входят в доли.

Живой список клиентов на сервер загружается отдельно и в git не коммитится:

```bash
python3 scripts/load_client_workbook.py "/path/SCO рабочий инструмент.xlsx"
```

Скрипт читает лист «кассы в сети по клиентам» (имя, страна, число касс КСО) и, где название совпало, лист «Клиенты SR10 х SCO» (магазины, регион, формат). Тестовые контуры пропускаются. Суточные чеки в книге не ведутся, поэтому SCO-001…SCO-006 остаются примером. CSV появляются в `data/live/`.

## Как поднять

Полная инструкция для нового стенда и для уже стоящего Superset — в [docs/apply.md](docs/apply.md). Короткий путь на машине с Docker:

```bash
cp .env.example .env
# заполнить POSTGRES_PASSWORD, SUPERSET_SECRET_KEY, SUPERSET_ADMIN_PASSWORD
docker compose up -d --build
python3 scripts/create_superset_assets.py
```

Повторный запуск скрипта удаляет три дашборда и собирает их заново. Том Postgres при этом не очищается. Порт снаружи один: `8088`. База наружу не публикуется.

## Как сменить демо-данные

Остановите контейнеры, удалите том и поднимите заново после замены CSV:

```bash
docker compose down -v
docker compose up -d
python3 scripts/create_superset_assets.py
```

Файлы:

- `data/chain.csv` — `id`, `name`;
- `data/store.csv` — `id`, `chain_id`, `name`, `has_sco` (`true` или `false`), `sco_registers`, `pos_registers`;
- `data/daily_store_metric.csv` — магазин, дата и семь метрик.

У магазина с `has_sco=false` касс КСО должно быть 0, и строк в суточном файле для него быть не должно. Генератор демо-данных: `python3 scripts/generate_demo_data.py`. Зерно фиксировано, контрольные суммы пишутся в `data/expected_30d.json`.
