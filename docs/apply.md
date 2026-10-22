# Как применить на своём Superset

Репозиторий переносит три отчёта: «Клиенты», «Магазины клиента», «Аутсайдеры». Формулы лежат в SQL и в метриках датасета, не в JS. Имена метрик и соответствие кодам требований — в [metrics.md](metrics.md).

Нужен Superset 4.1.2 и Postgres 16. В официальном образе Superset нет драйвера Postgres: `Dockerfile` ставит `psycopg2-binary==2.9.10`. На своём образе драйвер должен быть установлен отдельно.

## Поднять стенд из репозитория

На машине нужны Docker и Docker Compose. Пользователь входит в группу `docker`.

```bash
cp .env.example .env
# заполнить POSTGRES_PASSWORD, SUPERSET_SECRET_KEY, SUPERSET_ADMIN_PASSWORD
docker compose up -d --build
python3 scripts/create_superset_assets.py
```

Пустой том Postgres сам выполняет `sql/002_init.sh`: создаёт базу `analytics`, затем по порядку `sql/001_schema.sql`, `sql/003_load.sql`, `sql/004_client_attributes.sql`, `sql/005_norms.sql`. Повторный `docker compose up` эти файлы заново не прогоняет. На уже заполненном томе `004` и `005` применяют вручную, как в следующем разделе. `001` на заполненной базе целиком не запускают: он создаёт таблицы.

Скрипт ждёт `SUPERSET_URL/health` (по умолчанию из `.env`) и собирает подключение «Аналитика КСО», четыре датасета, графики и три дашборда. Повторный запуск удаляет дашборды с названиями «Клиенты», «Магазины клиента», «Аутсайдеры», датасеты `v_daily_fact`, `v_chain_outlier`, `v_store_outlier`, `v_threshold` и подключение «Аналитика КСО», затем создаёт их снова. Данные в Postgres при этом остаются.

Порт снаружи один: `8088`. База наружу не публикуется. Пароль администратора — `SUPERSET_ADMIN_PASSWORD` в `.env`, в git его нет.

Адреса после входа:

- `/superset/dashboard/clients/`
- `/superset/dashboard/stores/`
- `/superset/dashboard/outliers/`

## Уже есть свой Superset

1. Возьмите базу, до которой процесс Superset доходит по сети. Выполните SQL от имени владельца этой базы.
   - База пустая: `sql/001_schema.sql`, затем загрузка CSV в том же виде, что `sql/003_load.sql`, затем `sql/004_client_attributes.sql` и `sql/005_norms.sql`.
   - Таблицы `chain`, `store`, `daily_store_metric` уже есть: только `sql/004_client_attributes.sql` и `sql/005_norms.sql`. `001` не выполнять.
2. В `.env` укажите адрес своего Superset и хост базы так, как его видит процесс Superset, а не машина, с которой запущен скрипт. В compose из этого репозитория хост называется `postgres`.

```bash
SUPERSET_URL=https://superset.example
ANALYTICS_DB_HOST=postgres
ANALYTICS_DB_PORT=5432
ANALYTICS_DB_NAME=analytics
SUPERSET_DEFAULT_CHAIN=Сеть 002
SUPERSET_SKIP_VERIFY=1
python3 scripts/create_superset_assets.py
```

`ANALYTICS_SQLALCHEMY_URI` заменяет собранную строку целиком, если хост и пароль неудобно раскладывать по полям.

`SUPERSET_SKIP_VERIFY=1` нужен, когда в базе нет демо-сетей «Сеть 001»…«Сеть 150». Без этого флага скрипт после сборки сверяет демо-контрольные суммы и останавливается. Дашборды к этому моменту уже созданы.

`SUPERSET_DEFAULT_CHAIN` — сеть, выбранная в отчёте магазинов сразу после сборки. Для демо оставьте `Сеть 002`. Для своих данных поставьте имя сети из столбца `chain.name`.

В конфигурации Superset нужны `DASHBOARD_NATIVE_FILTERS` и `ENABLE_TEMPLATE_PROCESSING`. Для русских подписей — `BABEL_DEFAULT_LOCALE = "ru"`. Образец — `superset/superset_config.py`.

У датасета `v_daily_fact` должна остаться автоматическая метрика `count`. Её запрашивает фильтр. Если её удалить, фильтр отвечает `Metric 'count' does not exist`.

Пояснения на дашбордах — блоки Markdown. График типа markdown с этим датасетом даёт `Empty query`, потому что у него нет метрик и группировки.

## Куда класть суточные метрики

Одна строка — один магазин и один день. Столбцы файла `data/daily_store_metric.csv`:

`store_id`, `report_date`, `sco_receipts`, `pos_receipts`, `sco_annulled`, `pos_potential`, `sco_items_p95`, `sco_avg_duration_sec`, `sco_avg_annul_sec`.

Магазин без КСО в этот файл не пишется. У него `has_sco=false` и `sco_registers=0`. Его чеки в доли не входят.

Справочник:

- `chain.csv`: `id`, `name`. После `004` у сети есть ещё `country`, `region`, `store_format`. В трёх отчётах эти поля не показаны.
- `store.csv`: `id`, `chain_id`, `name`, `has_sco`, `sco_registers`, `pos_registers`.

В коде кассы и в JS этих имён нет. Пока поставка не названа своими полями, договорённость такая: код требования пишется в столбец Postgres из таблицы в [metrics.md](metrics.md). Superset читает уже эти столбцы.

Демо-файлы в `data/` — 150 сетей «Сеть 001»…«Сеть 150». Их собирает `python3 scripts/generate_demo_data.py`. Настоящий список клиентов и каталог `data/live/` в git не входят.

## Что скрипт выставляет сам

Менять это руками после сборки не нужно, если не хотите другой вид.

- Доли за период — метрики датасета `v_daily_fact`. Выражения записаны в `scripts/create_superset_assets.py`, список `DAILY_METRICS`.
- Аутсайдер и текст «Почему аутсайдер» — представления `v_chain_outlier` и `v_store_outlier`. Это не метрика Superset.
- Пороги в `report_threshold`: доля чеков КСО 30, доля аннуляций 2. Столбец перетока в таблице есть, в отбор аутсайдера не входит.
- Красный цвет `#E04355`: доля чеков КСО ниже 30, доля аннуляций выше 2, длительность чека выше 90 секунд, время аннуляции выше 120 секунд. Сравнивается уже процент и секунды, не доля от 0 до 1.
- В таблицах по 200 строк на страницу.
- Плашки — тип `big_number_total`, крупное число без второй подписи, высота ряда 16.
- Период по умолчанию на клиентах и магазинах: `2026-09-20 : 2026-10-20`. Это дни с 20.09.2026 по 19.10.2026 включительно.
- На аутсайдерах период — значение `period_name`: «7 дней», «30 дней» или «60 дней» от последней даты в данных. По умолчанию «30 дней».
- Фильтры аутсайдеров: период, «Доля КСО ниже порога» (`low_sco_share`), «Аннуляции выше порога» (`high_annul_share`), торговая сеть. Значения флагов — `да` и `нет`. Отдельного фильтра перетока нет.
