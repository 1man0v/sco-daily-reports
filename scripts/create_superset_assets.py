#!/usr/bin/env python3
"""Собирает в Superset подключение, датасеты и три отчёта. Повторный запуск заменяет их."""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIME_RANGE = "2026-09-20 : 2026-10-20"
COLUMN_KEYS = (
    "id", "column_name", "type", "verbose_name", "description",
    "filterable", "groupby", "is_dttm", "is_active", "python_date_format",
)
LABELS = {
    "period_name": "Период",
    "date_from": "Начало",
    "date_to_inclusive": "Конец",
    "chain_name": "Торговая сеть",
    "chain_id": "Код сети",
    "store_name": "Магазин",
    "store_id": "Код магазина",
    "report_date": "Дата",
    "stores_with_sco": "Магазинов с КСО",
    "stores_without_sco": "Магазинов без КСО",
    "stores_with_pos": "Магазинов с POS",
    "chain_sco_registers": "Касс КСО",
    "chain_pos_registers": "Касс POS",
    "sco_registers": "Касс КСО",
    "pos_registers": "Касс POS",
    "sco_receipts": "Чеки КСО",
    "pos_receipts": "Чеки POS",
    "sco_annulled": "Аннулированные чеки КСО",
    "pos_potential": "Потенциальные чеки POS",
    "sco_share_pct": "Доля чеков КСО, %",
    "annul_share_pct": "Доля аннуляций, %",
    "transfer_share_pct": "Доля перетока с POS, %",
    "sco_items_p95": "p95 товаров в чеке КСО",
    "sco_avg_duration_sec": "Средняя длительность чека КСО, сек",
    "sco_avg_annul_sec": "Среднее время аннуляции, сек",
    "low_sco_share": "Доля КСО ниже порога",
    "high_annul_share": "Аннуляции выше порога",
    "high_transfer_share": "Переток выше порога",
    "outlier_reason": "Почему аутсайдер",
    "sco_share_min_pct": "Порог доли чеков КСО, %",
    "annul_share_max_pct": "Порог доли аннуляций, %",
    "transfer_share_max_pct": "Порог доли перетока, %",
    "chain_count": "Торговых сетей",
}
DAILY_METRICS = [
    ("chain_count", "COUNT(DISTINCT chain_id)", "chain_count", ",.0f"),
    ("stores_with_sco", "MAX(stores_with_sco)", "stores_with_sco", ",.0f"),
    ("stores_without_sco", "MAX(stores_without_sco)", "stores_without_sco", ",.0f"),
    ("stores_with_pos", "MAX(stores_with_pos)", "stores_with_pos", ",.0f"),
    ("chain_sco_registers", "MAX(sco_registers_total)", "chain_sco_registers", ",.0f"),
    ("chain_pos_registers", "MAX(pos_registers_total)", "chain_pos_registers", ",.0f"),
    ("sco_registers", "MAX(sco_registers)", "sco_registers", ",.0f"),
    ("pos_registers", "MAX(pos_registers)", "pos_registers", ",.0f"),
    ("sco_receipts", "SUM(sco_receipts)", "sco_receipts", ",.0f"),
    ("pos_receipts", "SUM(pos_receipts)", "pos_receipts", ",.0f"),
    ("sco_annulled", "SUM(sco_annulled)", "sco_annulled", ",.0f"),
    ("pos_potential", "SUM(pos_potential)", "pos_potential", ",.0f"),
    ("sco_share_pct", "SUM(sco_receipts) * 100.0 / NULLIF(SUM(sco_receipts) + SUM(pos_receipts), 0)", "sco_share_pct", ",.1f"),
    ("annul_share_pct", "SUM(sco_annulled) * 100.0 / NULLIF(SUM(sco_receipts), 0)", "annul_share_pct", ",.1f"),
    ("transfer_share_pct", "SUM(pos_potential) * 100.0 / NULLIF(SUM(pos_receipts), 0)", "transfer_share_pct", ",.1f"),
    ("sco_items_p95", "SUM(sco_items_p95 * sco_receipts) / NULLIF(SUM(sco_receipts), 0)", "sco_items_p95", ",.1f"),
    ("sco_avg_duration_sec", "SUM(sco_avg_duration_sec * sco_receipts) / NULLIF(SUM(sco_receipts), 0)", "sco_avg_duration_sec", ",.1f"),
    ("sco_avg_annul_sec", "SUM(sco_avg_annul_sec * sco_annulled) / NULLIF(SUM(sco_annulled), 0)", "sco_avg_annul_sec", ",.1f"),
]
RED = "#E04355"
SHARE_FORMAT = [
    {"column": "sco_share_pct", "operator": "<", "targetValue": 30, "colorScheme": RED},
    {"column": "annul_share_pct", "operator": ">", "targetValue": 2, "colorScheme": RED},
]
STORE_FORMAT = SHARE_FORMAT + [
    {"column": "sco_avg_duration_sec", "operator": ">", "targetValue": 90, "colorScheme": RED},
    {"column": "sco_avg_annul_sec", "operator": ">", "targetValue": 120, "colorScheme": RED},
]


class Api:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.token = None
        self.csrf = None
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def __call__(self, method, path, payload=None, timeout=120):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        if payload is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if self.csrf:
            req.add_header("X-CSRFToken", self.csrf)
            req.add_header("Referer", self.base + "/")
        try:
            with self.opener.open(req, timeout=timeout) as response:
                raw = response.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise RuntimeError(f"{method} {path} -> {exc.code} {body[:2000]}") from exc


def load_env():
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def wait_health(base):
    for _ in range(60):
        try:
            with urllib.request.urlopen(base + "/health", timeout=5) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(5)
    raise RuntimeError("Superset не ответил на /health")


def login(api):
    body = api("POST", "/api/v1/security/login", {
        "username": "admin",
        "password": os.environ["SUPERSET_ADMIN_PASSWORD"],
        "provider": "db",
        "refresh": True,
    })
    api.token = body["access_token"]
    csrf = api("GET", "/api/v1/security/csrf_token/")
    api.csrf = csrf.get("result")


def listed(api, resource):
    body = api("GET", f"/api/v1/{resource}/?q=(page:0,page_size:200)")
    return body.get("result") or []


def cleanup(api):
    titles = {"Клиенты", "Магазины клиента", "Аутсайдеры"}
    for item in listed(api, "dashboard"):
        if item.get("dashboard_title") in titles:
            api("DELETE", f"/api/v1/dashboard/{item['id']}")
    for item in listed(api, "chart"):
        name = item.get("slice_name") or ""
        if name.startswith(("Клиенты —", "Магазины —", "Аутсайдеры —")):
            api("DELETE", f"/api/v1/chart/{item['id']}")
    for item in listed(api, "dataset"):
        if item.get("table_name") in {"v_daily_fact", "v_chain_outlier", "v_store_outlier", "v_threshold"}:
            api("DELETE", f"/api/v1/dataset/{item['id']}")
    for item in listed(api, "database"):
        if item.get("database_name") == "Аналитика КСО":
            api("DELETE", f"/api/v1/database/{item['id']}")


def object_id(body):
    if "id" in body:
        return body["id"]
    data = body.get("data") or body.get("result") or {}
    if isinstance(data, dict) and "id" in data:
        return data["id"]
    raise RuntimeError(f"no id in {json.dumps(body)[:500]}")


def create_database(api):
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.environ.get("ANALYTICS_DB_HOST", "postgres")
    port = os.environ.get("ANALYTICS_DB_PORT", "5432")
    name = os.environ.get("ANALYTICS_DB_NAME", "analytics")
    uri = os.environ.get("ANALYTICS_SQLALCHEMY_URI") or f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
    body = api("POST", "/api/v1/database/", {
        "database_name": "Аналитика КСО",
        "sqlalchemy_uri": uri,
        "expose_in_sqllab": True,
        "allow_run_async": False,
        "allow_ctas": False,
        "allow_cvas": False,
        "allow_dml": False,
        "configuration_method": "sqlalchemy_form",
    })
    return object_id(body)


def create_dataset(api, database_id, table_name, metrics, dttm_column):
    created = api("POST", "/api/v1/dataset/", {
        "database": database_id,
        "schema": "public",
        "table_name": table_name,
    })
    dataset_id = object_id(created)
    current = api("GET", f"/api/v1/dataset/{dataset_id}")["result"]
    columns = []
    for column in current["columns"]:
        slim = {key: column.get(key) for key in COLUMN_KEYS if key in column}
        slim["verbose_name"] = LABELS.get(column["column_name"], column.get("verbose_name"))
        slim["filterable"] = True
        slim["groupby"] = True
        slim["is_dttm"] = column["column_name"] in {dttm_column, "date_from", "date_to_inclusive", "report_date"}
        columns.append(slim)
    payload = {"columns": columns, "description": "Суточные агрегаты КСО. Доли считаются из сумм чеков."}
    if dttm_column:
        payload["main_dttm_col"] = dttm_column
    if metrics:
        payload["metrics"] = [
            {
                "metric_name": name,
                "expression": expression,
                "verbose_name": LABELS[label_key],
                "d3format": fmt,
                "metric_type": "metric",
            }
            for name, expression, label_key, fmt in metrics
        ]
    api("PUT", f"/api/v1/dataset/{dataset_id}", payload)
    return dataset_id


def create_chart(api, name, dataset_id, params):
    body = api("POST", "/api/v1/chart/", {
        "slice_name": name,
        "viz_type": params["viz_type"],
        "datasource_id": dataset_id,
        "datasource_type": "table",
        "params": json.dumps(params, ensure_ascii=False),
    })
    return object_id(body)


def big_number(api, name, dataset_id, metric, fmt, conditional_formatting=None):
    return create_chart(api, name, dataset_id, {
        "datasource": f"{dataset_id}__table",
        "viz_type": "big_number_total",
        "metric": metric,
        "granularity_sqla": "report_date",
        "time_range": TIME_RANGE,
        "y_axis_format": fmt,
        "header_font_size": 0.7,
        "subheader_font_size": 0.12,
        "subheader": "",
        "conditional_formatting": conditional_formatting or [],
    })


def aggregate_table(api, name, dataset_id, groupby, metrics, conditional_formatting=None, row_limit=500):
    return create_chart(api, name, dataset_id, {
        "datasource": f"{dataset_id}__table",
        "viz_type": "table",
        "query_mode": "aggregate",
        "groupby": groupby,
        "metrics": metrics,
        "percent_metrics": [],
        "adhoc_filters": [],
        "row_limit": row_limit,
        "order_desc": False,
        "include_search": True,
        "show_cell_bars": False,
        "color_pn": False,
        "page_length": 200,
        "granularity_sqla": "report_date",
        "time_range": TIME_RANGE,
        "table_timestamp_format": "%d.%m.%Y",
        "conditional_formatting": conditional_formatting or [],
    })


def raw_table(api, name, dataset_id, columns, conditional_formatting=None):
    return create_chart(api, name, dataset_id, {
        "datasource": f"{dataset_id}__table",
        "viz_type": "table",
        "query_mode": "raw",
        "all_columns": columns,
        "percent_metrics": [],
        "adhoc_filters": [],
        "order_by_cols": [],
        "row_limit": 2000,
        "include_search": True,
        "show_cell_bars": False,
        "color_pn": False,
        "page_length": 200,
        "table_timestamp_format": "%d.%m.%Y",
        "conditional_formatting": conditional_formatting or [],
    })


def layout(title, rows):
    position = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
        "HEADER_ID": {"id": "HEADER_ID", "type": "HEADER", "meta": {"text": title}},
    }
    for index, row in enumerate(rows):
        row_id = f"ROW-{index}"
        position["GRID_ID"]["children"].append(row_id)
        position[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for chart_index, cell in enumerate(row):
            if cell[0] == "md":
                _, width, height, text = cell
                key = f"MARKDOWN-{index}-{chart_index}"
                position[row_id]["children"].append(key)
                position[key] = {
                    "type": "MARKDOWN",
                    "id": key,
                    "children": [],
                    "parents": ["ROOT_ID", "GRID_ID", row_id],
                    "meta": {"width": width, "height": height, "code": text},
                }
                continue
            chart_id, width, height, chart_name = cell
            chart_key = f"CHART-{index}-{chart_index}"
            position[row_id]["children"].append(chart_key)
            position[chart_key] = {
                "type": "CHART",
                "id": chart_key,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {
                    "chartId": chart_id,
                    "width": width,
                    "height": height,
                    "sliceName": chart_name,
                },
            }
    return position


def time_filter(dataset_id, chart_ids):
    return {
        "id": "NATIVE_FILTER-time",
        "name": "Период",
        "filterType": "filter_time",
        "targets": [{"datasetId": dataset_id, "column": {"name": "report_date"}}],
        "defaultDataMask": {
            "extraFormData": {"time_range": TIME_RANGE},
            "filterState": {"value": TIME_RANGE},
        },
        "cascadeParentIds": [],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
        "type": "NATIVE_FILTER",
        "description": "20.09.2026–19.10.2026 по умолчанию",
        "chartsInScope": chart_ids,
        "tabsInScope": [],
        "controlValues": {"enableEmptyFilter": False},
    }


def select_filter(filter_id, name, dataset_ids, column, chart_ids, default=None, required=False):
    mask = {"extraFormData": {}, "filterState": {}, "ownState": {}}
    if default is not None:
        mask = {
            "extraFormData": {"filters": [{"col": column, "op": "IN", "val": [default]}]},
            "filterState": {"value": [default]},
        }
    return {
        "id": filter_id,
        "name": name,
        "filterType": "filter_select",
        "targets": [{"datasetId": dataset_id, "column": {"name": column}} for dataset_id in dataset_ids],
        "defaultDataMask": mask,
        "cascadeParentIds": [],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
        "type": "NATIVE_FILTER",
        "description": "",
        "chartsInScope": chart_ids,
        "tabsInScope": [],
        "controlValues": {
            "enableEmptyFilter": not required,
            "defaultToFirstItem": False,
            "multiSelect": False,
            "searchAllOptions": True,
            "inverseSelection": False,
        },
    }


def create_dashboard(api, title, slug, charts, filters):
    position = layout(title, charts)
    metadata = {
        "native_filter_configuration": filters,
        "timed_refresh_immune_slices": [],
        "expanded_slices": {},
        "refresh_frequency": 0,
        "color_scheme": "",
        "label_colors": {},
        "shared_label_colors": {},
        "cross_filters_enabled": False,
        "chart_configuration": {},
    }
    body = api("POST", "/api/v1/dashboard/", {
        "dashboard_title": title,
        "slug": slug,
        "published": True,
        "position_json": json.dumps(position, ensure_ascii=False),
        "json_metadata": json.dumps(metadata, ensure_ascii=False),
    })
    dashboard_id = object_id(body)
    for row in charts:
        for cell in row:
            if cell[0] == "md":
                continue
            chart_id = cell[0]
            api("PUT", f"/api/v1/chart/{chart_id}", {"dashboards": [dashboard_id]})
    return dashboard_id


def chart_data(api, dataset_id, columns, metrics, filters):
    query = {
        "columns": columns,
        "metrics": [
            {"label": name, "expressionType": "SQL", "sqlExpression": expression}
            for name, expression in metrics
        ],
        "filters": filters,
        "row_limit": 500,
        "orderby": [],
    }
    if not metrics:
        query["is_timeseries"] = False
    body = api("POST", "/api/v1/chart/data", {
        "datasource": {"id": dataset_id, "type": "table"},
        "force": True,
        "queries": [query],
        "result_format": "json",
        "result_type": "full",
    })
    return body["result"][0]


def verify(api, daily_id, chain_out_id, store_out_id):
    if os.environ.get("SUPERSET_SKIP_VERIFY") == "1":
        print("verify skipped")
        return
    expected = json.loads((ROOT / "data" / "expected_30d.json").read_text(encoding="utf-8"))
    date_filter = [{"col": "report_date", "op": "TEMPORAL_RANGE", "val": TIME_RANGE}]
    chains = chart_data(
        api,
        daily_id,
        ["chain_name"],
        [
            ("stores_with_sco", "MAX(stores_with_sco)"),
            ("stores_without_sco", "MAX(stores_without_sco)"),
            ("sco_share_pct", "SUM(sco_receipts) * 100.0 / NULLIF(SUM(sco_receipts) + SUM(pos_receipts), 0)"),
            ("annul_share_pct", "SUM(sco_annulled) * 100.0 / NULLIF(SUM(sco_receipts), 0)"),
            ("transfer_share_pct", "SUM(pos_potential) * 100.0 / NULLIF(SUM(pos_receipts), 0)"),
        ],
        date_filter,
    )["data"]
    by_name = {row["chain_name"]: row for row in chains}
    if len(by_name) != 150:
        raise RuntimeError(f"в отчёте клиентов {len(by_name)} сетей, ожидалось 150")
    for name in ("Сеть 001", "Сеть 002", "Сеть 007"):
        got = by_name[name]
        want = expected["chains"][name]
        for key in ("sco_share_pct", "annul_share_pct", "transfer_share_pct"):
            if abs(float(got[key]) - float(want[key])) > 0.05:
                raise RuntimeError(f"{name} {key}: superset {got[key]} json {want[key]}")
        for key in ("stores_with_sco", "stores_without_sco"):
            if int(got[key]) != int(want[key]):
                raise RuntimeError(f"{name} {key}: superset {got[key]} json {want[key]}")
    stores = chart_data(
        api,
        daily_id,
        ["store_name"],
        [("sco_receipts", "SUM(sco_receipts)")],
        date_filter + [{"col": "chain_name", "op": "IN", "val": ["Сеть 002"]}],
    )["data"]
    names = {row["store_name"] for row in stores}
    if len(names) != 6:
        raise RuntimeError(f"у Сети 002 в отчёте {len(names)} магазинов с КСО, ожидалось 6")
    if "Сеть 002 — магазин 01" in names or "Сеть 002 — магазин 02" in names:
        raise RuntimeError("магазин без КСО попал в расчёт Сети 002")
    outliers = chart_data(
        api,
        chain_out_id,
        ["chain_name", "sco_share_pct", "outlier_reason"],
        [],
        [{"col": "period_name", "op": "IN", "val": ["30 дней"]}],
    )["data"]
    outlier_names = {row["chain_name"] for row in outliers}
    if "Сеть 007" not in outlier_names or "Сеть 001" in outlier_names:
        raise RuntimeError("Сеть 007 должна быть аутсайдером, Сеть 001 нет")
    store_outliers = chart_data(
        api,
        store_out_id,
        ["store_name"],
        [],
        [
            {"col": "period_name", "op": "IN", "val": ["30 дней"]},
            {"col": "chain_name", "op": "IN", "val": ["Сеть 002"]},
        ],
    )["data"]
    if store_outliers:
        raise RuntimeError("Сеть 002 не должна попадать в аутсайдеры магазинов за 30 дней")
    print("verify ok", f"chains {len(by_name)}", f"outliers {len(outlier_names)}")


def main():
    load_env()
    base = os.environ.get("SUPERSET_URL", "http://172.29.17.3:8088")
    wait_health(base)
    api = Api(base)
    login(api)
    cleanup(api)
    database_id = create_database(api)
    daily_id = create_dataset(api, database_id, "v_daily_fact", DAILY_METRICS, "report_date")
    chain_out_id = create_dataset(api, database_id, "v_chain_outlier", [], None)
    store_out_id = create_dataset(api, database_id, "v_store_outlier", [], None)
    threshold_id = create_dataset(api, database_id, "v_threshold", [], None)

    clients_md = ("md", 12, 22, """
В доли входят только магазины с кассами самообслуживания. Магазины без КСО в доли не входят. Число касс и магазинов с POS берётся по всей сети.

Доля чеков КСО = сумма чеков КСО / (чеки КСО + чеки POS). Доля аннуляций = аннулированные чеки КСО / чеки КСО. Доля перетока = потенциальные чеки POS (до 10 товаров, не наличные) / чеки POS. За период складываются чеки, а не дневные проценты.

Красным отмечено значение хуже нормы: доля чеков КСО ниже 30%, доля аннуляций выше 2%.
""")
    clients_chains = big_number(api, "Торговых сетей", daily_id, "chain_count", ",.0f")
    clients_share = big_number(api, "Доля чеков КСО", daily_id, "sco_share_pct", ",.1f", [SHARE_FORMAT[0]])
    clients_annul = big_number(api, "Доля аннуляций", daily_id, "annul_share_pct", ",.1f", [SHARE_FORMAT[1]])
    clients_transfer = big_number(api, "Доля перетока", daily_id, "transfer_share_pct", ",.1f")
    clients_table = aggregate_table(
        api, "Клиенты — таблица", daily_id, ["chain_name"],
        ["sco_share_pct", "annul_share_pct", "transfer_share_pct", "stores_with_sco", "chain_sco_registers", "stores_with_pos", "chain_pos_registers"],
        SHARE_FORMAT,
    )
    client_charts = [clients_chains, clients_share, clients_annul, clients_transfer, clients_table]
    create_dashboard(api, "Клиенты", "clients", [
        [clients_md],
        [(clients_chains, 3, 16, "Торговых сетей"), (clients_share, 3, 16, "Доля чеков КСО"), (clients_annul, 3, 16, "Доля аннуляций"), (clients_transfer, 3, 16, "Доля перетока")],
        [(clients_table, 12, 120, "Таблица")],
    ], [time_filter(daily_id, client_charts)])

    stores_md = ("md", 12, 24, """
Выберите сеть сверху. В таблице магазины этой сети, у которых есть КСО.

p95 товаров, средняя длительность чека и среднее время аннуляции за период — среднее дневных значений с весом по чекам. Это не новый p95 по сырым чекам: в суточном агрегате сырых чеков нет.

Красным отмечено значение хуже нормы: доля чеков КСО ниже 30%, доля аннуляций выше 2%, длительность чека выше 90 секунд, время аннуляции выше 120 секунд.
""")
    stores_with = big_number(api, "Магазинов с КСО", daily_id, "stores_with_sco", ",.0f")
    stores_without = big_number(api, "Магазинов без КСО", daily_id, "stores_without_sco", ",.0f")
    stores_share = big_number(api, "Доля чеков КСО", daily_id, "sco_share_pct", ",.1f", [SHARE_FORMAT[0]])
    stores_annul = big_number(api, "Доля аннуляций", daily_id, "annul_share_pct", ",.1f", [SHARE_FORMAT[1]])
    stores_transfer = big_number(api, "Доля перетока", daily_id, "transfer_share_pct", ",.1f")
    stores_table = aggregate_table(
        api, "Магазины — таблица", daily_id, ["store_name"],
        [
            "sco_registers", "pos_registers",
            "sco_share_pct", "annul_share_pct", "transfer_share_pct",
            "sco_receipts", "pos_receipts",
            "sco_items_p95", "sco_avg_duration_sec",
            "pos_potential",
            "sco_annulled", "sco_avg_annul_sec",
        ],
        STORE_FORMAT,
        row_limit=3000,
    )
    store_charts = [stores_with, stores_without, stores_share, stores_annul, stores_transfer, stores_table]
    create_dashboard(api, "Магазины клиента", "stores", [
        [stores_md],
        [(stores_with, 6, 16, "Магазинов с КСО"), (stores_without, 6, 16, "Магазинов без КСО")],
        [(stores_share, 4, 16, "Доля чеков КСО"), (stores_annul, 4, 16, "Доля аннуляций"), (stores_transfer, 4, 16, "Доля перетока")],
        [(stores_table, 12, 110, "Таблица")],
    ], [
        select_filter("NATIVE_FILTER-chain", "Торговая сеть", [daily_id], "chain_name", store_charts, default=os.environ.get("SUPERSET_DEFAULT_CHAIN", "Сеть 002"), required=True),
        time_filter(daily_id, store_charts),
    ])

    outliers_md = ("md", 12, 28, """
Сеть или магазин попадает сюда, если за весь выбранный период доля чеков КСО ниже 30% или доля аннуляций выше 2%. Столбец «Почему аутсайдер» собирается в базе: в него попадают только те условия, которые сработали.

У доли перетока числовой нормы нет, поэтому она в причину не входит. «30 дней» совпадает с периодом по умолчанию на странице клиентов: 20.09.2026–19.10.2026.
""")
    threshold_table = raw_table(
        api, "Аутсайдеры — пороги", threshold_id,
        ["sco_share_min_pct", "annul_share_max_pct"],
    )
    chain_table = raw_table(
        api, "Аутсайдеры — сети", chain_out_id,
        ["chain_name", "sco_share_pct", "annul_share_pct", "transfer_share_pct", "stores_with_sco", "stores_without_sco", "outlier_reason"],
        SHARE_FORMAT,
    )
    store_table = raw_table(
        api, "Аутсайдеры — магазины", store_out_id,
        ["chain_name", "store_name", "sco_share_pct", "annul_share_pct", "transfer_share_pct", "sco_items_p95", "sco_avg_duration_sec", "sco_avg_annul_sec", "outlier_reason"],
        STORE_FORMAT,
    )
    outlier_charts = [chain_table, store_table]
    create_dashboard(api, "Аутсайдеры", "outliers", [
        [outliers_md],
        [(threshold_table, 12, 14, "Пороги")],
        [(chain_table, 12, 90, "Сети")],
        [(store_table, 12, 90, "Магазины")],
    ], [
        select_filter("NATIVE_FILTER-period", "Период", [chain_out_id, store_out_id], "period_name", outlier_charts, default="30 дней", required=True),
        select_filter("NATIVE_FILTER-low", "Доля КСО ниже порога", [chain_out_id, store_out_id], "low_sco_share", outlier_charts),
        select_filter("NATIVE_FILTER-annul", "Аннуляции выше порога", [chain_out_id, store_out_id], "high_annul_share", outlier_charts),
        select_filter("NATIVE_FILTER-outchain", "Торговая сеть", [chain_out_id, store_out_id], "chain_name", outlier_charts),
    ])

    verify(api, daily_id, chain_out_id, store_out_id)
    print(base + "/superset/dashboard/clients/")
    print(base + "/superset/dashboard/stores/")
    print(base + "/superset/dashboard/outliers/")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(exc, file=sys.stderr)
        raise
