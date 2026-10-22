#!/usr/bin/env python3
"""Берёт клиентов из книги «SCO рабочий инструмент».

Лист «кассы в сети по клиентам»: имя, страна, число касс КСО.
Лист «Клиенты SR10 х SCO»: число магазинов, регион и формат, если название совпало.
Чеки SCO-001…SCO-006 в книге нет, они по-прежнему считаются примером.
Результат пишется в data/live/ и в git не входит.
"""
import csv
import json
import random
import re
import sys
import zipfile
import zlib
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "live"
START = date(2026, 8, 21)
DAYS = 60
PERIOD_FROM = date(2026, 9, 20)
PERIOD_TO = date(2026, 10, 20)
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SKIP = {"тестовыйконтур", "тестоваясреда"}


def norm(value):
    value = (value or "").casefold().replace("ё", "е").replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-zа-я0-9]+", "", value)


def clamp(value, low, high):
    return max(low, min(high, value))


# Сети, где на магазин с КСО приходится в среднем 7 касс. Остальные — 3, 4 или 5.
DENSE_TOKENS = ("гиперглобус", "лента", "реми", "невада")


def name_tokens(name):
    folded = name.casefold().replace("ё", "е")
    return [part for part in re.split(r"[^a-zа-я0-9]+", folded) if part]


def sco_density(name, chain_id):
    tokens = set(name_tokens(name))
    if tokens.intersection(DENSE_TOKENS):
        return 7
    return 3 + (zlib.crc32(chain_id.encode()) % 3)


# Первые магазины сети специально разные, чтобы в таблице были и норма, и отклонения.
SHOWCASE = {
    2: ("low", "strong"),
    3: ("low", "annul", "healthy"),
    4: ("low", "annul", "slow", "healthy"),
    5: ("low", "annul", "slow", "long_annul", "strong"),
}
FULL_SHOWCASE = ("low", "annul", "slow", "long_annul", "strong", "healthy")


def profile_kind(rng, client, store_index, sco_count):
    if sco_count >= 6 and store_index <= len(FULL_SHOWCASE):
        return FULL_SHOWCASE[store_index - 1]
    if store_index <= sco_count and sco_count in SHOWCASE:
        return SHOWCASE[sco_count][store_index - 1]
    roll = rng.random()
    low_until = 0.28 if client["low_share"] else 0.16
    annul_until = low_until + (0.26 if client["high_annul"] else 0.14)
    slow_until = annul_until + 0.12
    long_annul_until = slow_until + 0.10
    strong_until = long_annul_until + 0.14
    if roll < low_until:
        return "low"
    if roll < annul_until:
        return "annul"
    if roll < slow_until:
        return "slow"
    if roll < long_annul_until:
        return "long_annul"
    if roll < strong_until:
        return "strong"
    return "healthy"


def store_rates(rng, client, store_index, sco_count):
    """Профиль магазина внутри сети. Сеть задаёт склонность, магазины расходятся."""
    kind = profile_kind(rng, client, store_index, sco_count)
    if kind == "low":
        share, annul, transfer = rng.uniform(0.06, 0.24), rng.uniform(0.005, 0.018), rng.uniform(0.38, 0.82)
        p95, duration, annul_sec = rng.uniform(2.5, 8), rng.uniform(40, 80), rng.uniform(15, 70)
    elif kind == "annul":
        share, annul, transfer = rng.uniform(0.34, 0.62), rng.uniform(0.045, 0.14), rng.uniform(0.1, 0.55)
        p95, duration, annul_sec = rng.uniform(5, 14), rng.uniform(40, 80), rng.uniform(40, 100)
    elif kind == "slow":
        share, annul, transfer = rng.uniform(0.34, 0.66), rng.uniform(0.004, 0.016), rng.uniform(0.1, 0.5)
        p95, duration, annul_sec = rng.uniform(10, 28), rng.uniform(110, 210), rng.uniform(20, 80)
    elif kind == "long_annul":
        share, annul, transfer = rng.uniform(0.34, 0.64), rng.uniform(0.006, 0.018), rng.uniform(0.1, 0.5)
        p95, duration, annul_sec = rng.uniform(4, 14), rng.uniform(40, 80), rng.uniform(140, 230)
    elif kind == "strong":
        share, annul, transfer = rng.uniform(0.64, 0.88), rng.uniform(0.003, 0.012), rng.uniform(0.05, 0.25)
        p95, duration, annul_sec = rng.uniform(2.5, 7), rng.uniform(25, 55), rng.uniform(8, 35)
    else:
        share, annul, transfer = rng.uniform(0.36, 0.62), rng.uniform(0.004, 0.014), rng.uniform(0.08, 0.46)
        p95, duration, annul_sec = rng.uniform(4, 14), rng.uniform(38, 75), rng.uniform(12, 70)
    if client["high_transfer"]:
        transfer = clamp(transfer + 0.15, 0.05, 0.92)
    return share, annul, transfer, p95, duration, annul_sec, rng.uniform(0.35, 2.6)


def spread(total, count):
    if count <= 0:
        return []
    base, extra = divmod(int(total), count)
    return [base + (1 if i < extra else 0) for i in range(count)]


def load_shared_strings(book):
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    return ["".join((node.text or "") for node in item.iter(f"{NS}t")) for item in root.findall(f"{NS}si")]


def sheet_path(book, title):
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    workbook = ET.fromstring(book.read("xl/workbook.xml"))
    rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    for sheet in workbook.findall("m:sheets/m:sheet", ns):
        if sheet.attrib.get("name", "").strip() == title.strip():
            target = targets[sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
            return "xl/" + target.lstrip("/")
    raise SystemExit(f"нет листа {title}")


def sheet_rows(book, strings, path):
    root = ET.fromstring(book.read(path))
    rows = {}

    def colrow(ref):
        letters = "".join(ch for ch in ref if ch.isalpha())
        number = int("".join(ch for ch in ref if ch.isdigit()))
        index = 0
        for ch in letters:
            index = index * 26 + ord(ch) - 64
        return index, number

    for cell in root.iter(f"{NS}c"):
        ref = cell.attrib.get("r")
        if not ref:
            continue
        column, row = colrow(ref)
        kind = cell.attrib.get("t")
        value_node = cell.find(f"{NS}v")
        inline = cell.find(f"{NS}is")
        value = ""
        if kind == "s" and value_node is not None and value_node.text:
            value = strings[int(value_node.text)]
        elif kind == "inlineStr" and inline is not None:
            value = "".join(node.text or "" for node in inline.iter(f"{NS}t"))
        elif value_node is not None and value_node.text:
            value = value_node.text
        rows.setdefault(row, {})[column] = value.strip()
    return rows


def display_name(raw):
    name = re.sub(r"\s*\(\.\.\.[^)]+\)", "", raw)
    name = re.sub(r"\s*\(осн\.\)\s*$", "", name).strip()
    return name or raw.strip()


def client_code(raw, fallback):
    match = re.search(r"\(\.\.\.([A-Za-z0-9]+)\)", raw)
    return match.group(1) if match else fallback


def number(value):
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def read_clients(path):
    book = zipfile.ZipFile(path)
    strings = load_shared_strings(book)
    installed = defaultdict(lambda: {"sco_registers": 0, "country": "", "raw": ""})
    for row_number, cols in sheet_rows(book, strings, sheet_path(book, "кассы в сети по клиентам")).items():
        if row_number < 3 or not cols.get(4):
            continue
        raw = cols[4]
        if norm(display_name(raw)) in SKIP or norm(raw) in SKIP:
            continue
        qty = number(cols.get(5)) or 0
        if qty <= 0:
            continue
        installed[raw]["sco_registers"] += qty
        installed[raw]["country"] = cols.get(3, "")
        installed[raw]["raw"] = raw

    directory = {}
    for row_number, cols in sheet_rows(book, strings, sheet_path(book, "Клиенты SR10 х SCO")).items():
        if row_number < 5 or not cols.get(2):
            continue
        directory[norm(cols[2])] = {
            "stores": number(cols.get(10)),
            "all_registers": number(cols.get(9)),
            "region": cols.get(3, ""),
            "store_format": cols.get(11, ""),
            "source_name": cols[2],
        }
    return installed, directory


def match_directory(name, directory):
    parts = [name, *re.split(r"\s*/\s*", name)]
    for part in parts:
        found = directory.get(norm(part))
        if found:
            return found
    return None


def build(path):
    installed, directory = read_clients(path)
    merged = {}
    for raw, item in installed.items():
        name = display_name(raw)
        bucket = merged.setdefault(name, {"name": name, "raw": raw, "country": item["country"], "sco_registers": 0})
        bucket["sco_registers"] += item["sco_registers"]
        if item["sco_registers"] >= bucket.get("_lead", 0):
            bucket["_lead"] = item["sco_registers"]
            bucket["raw"] = raw
            bucket["country"] = item["country"]
    clients = []
    seen_ids = set()
    for index, name in enumerate(sorted(merged), start=1):
        item = merged[name]
        code = client_code(item["raw"], f"c{index:03d}")
        if code in seen_ids:
            code = f"{code}-{index}"
        seen_ids.add(code)
        info = match_directory(name, directory)
        sco_registers = item["sco_registers"]
        stores_total = info["stores"] if info and info["stores"] else None
        density = sco_density(name, code)
        if sco_registers <= 0:
            with_sco = 0
            without_sco = stores_total or 0
        else:
            # Столько магазинов нужно, чтобы на магазин с КСО пришлось density касс.
            with_sco = min(sco_registers, max(1, int(round(sco_registers / density))))
            if stores_total and stores_total > with_sco:
                without_sco = stores_total - with_sco
            else:
                # В книге магазины без КСО не выделены. Если справочник не больше
                # числа магазинов с КСО, добавляем около одного такого магазина на пять.
                without_sco = max(1, int(round(with_sco * 0.2)))
        if info and info["all_registers"] and info["all_registers"] > sco_registers:
            pos_registers = info["all_registers"] - sco_registers
            pos_source = "кассы из листа Клиенты SR10 х SCO минус КСО"
        else:
            pos_registers = max(with_sco + without_sco, sco_registers)
            pos_source = "в книге нет отдельного числа POS, взято не меньше числа магазинов"
        clients.append({
            "id": code,
            "name": name,
            "country": item["country"],
            "region": (info or {}).get("region", ""),
            "store_format": (info or {}).get("store_format", ""),
            "sco_registers": sco_registers,
            "with_sco": with_sco,
            "without_sco": without_sco,
            "pos_registers": pos_registers,
            "pos_source": pos_source,
            "matched": bool(info),
            "low_share": index % 7 == 0,
            "high_annul": index % 11 == 0,
            "high_transfer": index % 5 == 0,
        })
    return clients


def write_tables(clients):
    rng = random.Random(20261020)
    OUT.mkdir(parents=True, exist_ok=True)
    chains, stores, metrics = [], [], []
    for client in clients:
        chains.append({
            "id": client["id"],
            "name": client["name"],
            "country": client["country"],
            "region": client["region"],
            "store_format": client["store_format"],
        })
        sco_spread = spread(client["sco_registers"], client["with_sco"])
        pos_spread = spread(client["pos_registers"], client["with_sco"] + client["without_sco"])
        total_stores = client["with_sco"] + client["without_sco"]
        for store_index in range(1, total_stores + 1):
            has_sco = store_index <= client["with_sco"]
            sco_registers = sco_spread[store_index - 1] if has_sco else 0
            pos_registers = pos_spread[store_index - 1] if store_index - 1 < len(pos_spread) else 0
            if has_sco and pos_registers < 1:
                pos_registers = 1
            if not has_sco and pos_registers < 1:
                pos_registers = 1
            store_id = f"{client['id']}-{store_index:04d}"
            stores.append({
                "id": store_id,
                "chain_id": client["id"],
                "name": f"Магазин {store_index:04d}",
                "has_sco": "true" if has_sco else "false",
                "sco_registers": sco_registers,
                "pos_registers": pos_registers,
            })
            if not has_sco:
                continue
            share_p, annul_p, transfer_p, p95, duration, annul_sec, busy = store_rates(
                rng, client, store_index, client["with_sco"]
            )
            for offset in range(DAYS):
                day = START + timedelta(days=offset)
                volume = (sco_registers * rng.randint(40, 120) + pos_registers * rng.randint(30, 110)) * busy
                if day.weekday() >= 5:
                    volume *= 1.3
                volume = max(2, int(volume))
                share = clamp(share_p + rng.uniform(-0.02, 0.02), 0.04, 0.9)
                annul_rate = clamp(annul_p + rng.uniform(-0.004, 0.004), 0.001, 0.2)
                transfer_rate = clamp(transfer_p + rng.uniform(-0.03, 0.03), 0.04, 0.92)
                sco_receipts = max(1, int(round(volume * share)))
                pos_receipts = max(1, int(round(volume * (1 - share))))
                metrics.append({
                    "store_id": store_id,
                    "report_date": day.isoformat(),
                    "sco_receipts": sco_receipts,
                    "pos_receipts": pos_receipts,
                    "sco_annulled": min(sco_receipts, int(round(sco_receipts * annul_rate))),
                    "pos_potential": min(pos_receipts, int(round(pos_receipts * transfer_rate))),
                    "sco_items_p95": round(clamp(p95 + rng.uniform(-1.2, 1.2), 1, 40), 2),
                    "sco_avg_duration_sec": round(clamp(duration + rng.uniform(-8, 8), 15, 300), 1),
                    "sco_avg_annul_sec": round(clamp(annul_sec + rng.uniform(-8, 8), 5, 240), 1),
                })
    write_csv(OUT / "chain.csv", ["id", "name", "country", "region", "store_format"], chains)
    write_csv(OUT / "store.csv", ["id", "chain_id", "name", "has_sco", "sco_registers", "pos_registers"], stores)
    write_csv(
        OUT / "daily_store_metric.csv",
        ["store_id", "report_date", "sco_receipts", "pos_receipts", "sco_annulled", "pos_potential", "sco_items_p95", "sco_avg_duration_sec", "sco_avg_annul_sec"],
        metrics,
    )
    write_csv(
        OUT / "clients_used.csv",
        ["id", "name", "country", "region", "store_format", "sco_registers", "with_sco", "without_sco", "pos_registers", "pos_source", "matched"],
        clients,
    )
    return len(metrics)


def write_csv(path, fieldnames, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "/Users/imanov/Downloads/SCO рабочий инструмент.xlsx")
    clients = build(source)
    metric_rows = write_tables(clients)
    matched = sum(1 for client in clients if client["matched"])
    without = sum(1 for client in clients if client["without_sco"])
    print(f"clients {len(clients)} matched_store_counts {matched} chains_with_stores_without_sco {without}")
    print(f"sco_registers {sum(c['sco_registers'] for c in clients)} stores {sum(c['with_sco']+c['without_sco'] for c in clients)} metric_rows {metric_rows}")
    sample = sorted(clients, key=lambda item: -item["sco_registers"])[:8]
    for client in sample:
        print(f"{client['sco_registers']:6} with {client['with_sco']:5} without {client['without_sco']:5} {client['country']:3} {client['name']}")


if __name__ == "__main__":
    main()
