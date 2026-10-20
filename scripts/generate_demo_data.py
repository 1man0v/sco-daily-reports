#!/usr/bin/env python3
"""Демо-суточные агрегаты для 150 сетей, пока нет настоящего списка клиентов.

Зерно фиксировано: один и тот же запуск даёт те же CSV.
Магазин без КСО не получает строк в daily_store_metric.
"""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
START = date(2026, 8, 21)
DAYS = 60
PERIOD_FROM = date(2026, 9, 20)  # включительно, 30 дней до 19.10.2026
PERIOD_TO = date(2026, 10, 20)   # не включая


def clamp(value, low, high):
    return max(low, min(high, value))


def main():
    rng = random.Random(20261020)
    DATA.mkdir(parents=True, exist_ok=True)
    chains = []
    stores = []
    metrics = []
    flags = {}

    for i in range(1, 151):
        chain_id = f"c{i:03d}"
        chain_name = f"Сеть {i:03d}"
        low_share = i % 7 == 0
        high_annul = i % 11 == 0
        high_transfer = i % 5 == 0
        flags[chain_name] = {
            "low_share": low_share,
            "high_annul": high_annul,
            "high_transfer": high_transfer,
        }
        sco_p = rng.uniform(0.14, 0.26) if low_share else rng.uniform(0.36, 0.58)
        annul_p = rng.uniform(0.045, 0.08) if high_annul else rng.uniform(0.008, 0.022)
        transfer_p = rng.uniform(0.48, 0.68) if high_transfer else rng.uniform(0.15, 0.34)
        p95 = rng.uniform(6, 14)
        duration = rng.uniform(50, 100)
        annul_sec = rng.uniform(20, 60)
        n_stores = 6 + (i % 10)
        n_without = 0 if i % 10 == 1 else max(1, n_stores // 3)
        chains.append({"id": chain_id, "name": chain_name})
        for j in range(1, n_stores + 1):
            has_sco = j > n_without
            store_id = f"s{i:03d}-{j:02d}"
            store_name = f"Сеть {i:03d} — магазин {j:02d}"
            sco_registers = rng.randint(2, 8) if has_sco else 0
            pos_registers = rng.randint(2, 6)
            stores.append({
                "id": store_id,
                "chain_id": chain_id,
                "name": store_name,
                "has_sco": "true" if has_sco else "false",
                "sco_registers": sco_registers,
                "pos_registers": pos_registers,
            })
            if not has_sco:
                continue
            for offset in range(DAYS):
                day = START + timedelta(days=offset)
                weekend = day.weekday() >= 5
                volume = sco_registers * rng.randint(45, 110) + pos_registers * rng.randint(40, 100)
                if weekend:
                    volume = int(volume * 1.3)
                share = clamp(sco_p + rng.uniform(-0.015, 0.015), 0.05, 0.85)
                annul_rate = clamp(annul_p + rng.uniform(-0.004, 0.004), 0.001, 0.2)
                transfer_rate = clamp(transfer_p + rng.uniform(-0.02, 0.02), 0.05, 0.9)
                sco_receipts = max(1, int(round(volume * share)))
                pos_receipts = max(1, int(round(volume * (1 - share))))
                sco_annulled = min(sco_receipts, int(round(sco_receipts * annul_rate)))
                pos_potential = min(pos_receipts, int(round(pos_receipts * transfer_rate)))
                metrics.append({
                    "store_id": store_id,
                    "report_date": day.isoformat(),
                    "sco_receipts": sco_receipts,
                    "pos_receipts": pos_receipts,
                    "sco_annulled": sco_annulled,
                    "pos_potential": pos_potential,
                    "sco_items_p95": round(clamp(p95 + rng.uniform(-1, 1), 1, 40), 2),
                    "sco_avg_duration_sec": round(clamp(duration + rng.uniform(-8, 8), 15, 300), 1),
                    "sco_avg_annul_sec": round(clamp(annul_sec + rng.uniform(-5, 5), 5, 180), 1),
                })

    write_csv(DATA / "chain.csv", ["id", "name"], chains)
    write_csv(
        DATA / "store.csv",
        ["id", "chain_id", "name", "has_sco", "sco_registers", "pos_registers"],
        stores,
    )
    write_csv(
        DATA / "daily_store_metric.csv",
        [
            "store_id", "report_date", "sco_receipts", "pos_receipts", "sco_annulled",
            "pos_potential", "sco_items_p95", "sco_avg_duration_sec", "sco_avg_annul_sec",
        ],
        metrics,
    )

    store_chain = {row["id"]: row["chain_id"] for row in stores}
    chain_name = {row["id"]: row["name"] for row in chains}
    sco_stores = {row["id"]: 0 for row in chains}
    plain_stores = {row["id"]: 0 for row in chains}
    for row in stores:
        if row["has_sco"] == "true":
            sco_stores[row["chain_id"]] += 1
        else:
            plain_stores[row["chain_id"]] += 1

    totals = {}
    for row in metrics:
        day = date.fromisoformat(row["report_date"])
        if not (PERIOD_FROM <= day < PERIOD_TO):
            continue
        cid = store_chain[row["store_id"]]
        bucket = totals.setdefault(cid, {"sco": 0, "pos": 0, "annul": 0, "potential": 0})
        bucket["sco"] += row["sco_receipts"]
        bucket["pos"] += row["pos_receipts"]
        bucket["annul"] += row["sco_annulled"]
        bucket["potential"] += row["pos_potential"]

    expected = {"period_from": PERIOD_FROM.isoformat(), "period_to_exclusive": PERIOD_TO.isoformat(), "chains": {}}
    crossed = []
    outlier_names = []
    for cid, bucket in totals.items():
        name = chain_name[cid]
        sco_share = bucket["sco"] * 100 / (bucket["sco"] + bucket["pos"])
        annul_share = bucket["annul"] * 100 / bucket["sco"]
        transfer_share = bucket["potential"] * 100 / bucket["pos"]
        expected["chains"][name] = {
            "sco_receipts": bucket["sco"],
            "pos_receipts": bucket["pos"],
            "sco_annulled": bucket["annul"],
            "pos_potential": bucket["potential"],
            "sco_share_pct": sco_share,
            "annul_share_pct": annul_share,
            "transfer_share_pct": transfer_share,
            "stores_with_sco": sco_stores[cid],
            "stores_without_sco": plain_stores[cid],
        }
        flag = flags[name]
        is_outlier = sco_share < 30 or annul_share > 3 or transfer_share > 40
        if is_outlier:
            outlier_names.append(name)
        if flag["low_share"] and sco_share >= 30:
            crossed.append(f"{name} задуман как низкая доля, факт {sco_share:.2f}")
        if not flag["low_share"] and sco_share < 30:
            crossed.append(f"{name} задуман как нормальная доля, факт {sco_share:.2f}")
        if flag["high_annul"] and annul_share <= 3:
            crossed.append(f"{name} задуман как высокие аннуляции, факт {annul_share:.2f}")
        if not flag["high_annul"] and annul_share > 3:
            crossed.append(f"{name} задуман как обычные аннуляции, факт {annul_share:.2f}")
        if flag["high_transfer"] and transfer_share <= 40:
            crossed.append(f"{name} задуман как высокий переток, факт {transfer_share:.2f}")
        if not flag["high_transfer"] and transfer_share > 40:
            crossed.append(f"{name} задуман как обычный переток, факт {transfer_share:.2f}")

    expected["outlier_chains_30d"] = len(outlier_names)
    (DATA / "expected_30d.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"chains {len(chains)} stores {len(stores)} metric rows {len(metrics)}")
    print(f"outliers in 30d {len(outlier_names)}")
    sample = expected["chains"]["Сеть 001"]
    print(
        "Сеть 001",
        f"sco {sample['sco_share_pct']:.2f}",
        f"annul {sample['annul_share_pct']:.2f}",
        f"transfer {sample['transfer_share_pct']:.2f}",
        f"with {sample['stores_with_sco']} without {sample['stores_without_sco']}",
    )
    low = expected["chains"]["Сеть 007"]
    print(
        "Сеть 007",
        f"sco {low['sco_share_pct']:.2f}",
        f"annul {low['annul_share_pct']:.2f}",
        f"transfer {low['transfer_share_pct']:.2f}",
    )
    if crossed:
        print("CROSSED")
        for line in crossed:
            print(line)
        raise SystemExit(1)


def write_csv(path, fieldnames, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
