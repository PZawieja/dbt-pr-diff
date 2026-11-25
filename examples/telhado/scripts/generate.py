#!/usr/bin/env python3
import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEEDS = Path(__file__).resolve().parent.parent / "seeds"
START = date(2026, 8, 17)
DAYS = 90
REGIONS = ["Lisboa", "Porto", "Algarve", "Coimbra", "Braga"]
INVERTER_MODELS = ["SolarEdge SE5K", "Fronius Primo 6.0", "Huawei SUN2000-8K"]
# installed/peak ratios pinned so the capacity-factor change in the post reproduces
PINNED_RATIOS = {"PRT-001": 0.89, "PRT-014": 1.0, "PRT-027": 1.152}


def write(name: str, header: list[str], rows: list[list]) -> None:
    with (SEEDS / f"{name}.csv").open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def main() -> None:
    rng = random.Random(42)
    sites, inverters, readings = [], [], []
    inverter_seq = 0
    reading_seq = 0
    for n in range(1, 31):
        site_id = f"PRT-{n:03d}"
        peak_kw = round(rng.uniform(4.0, 12.0), 2)
        ratio = PINNED_RATIOS.get(site_id, rng.choice([0.95, 1.0, 1.0, 1.05, 1.1]))
        installed_kw = round(peak_kw * ratio, 2)
        commissioned = date(2024, 1, 1) + timedelta(days=rng.randint(0, 540))
        sites.append(
            [site_id, f"Telhado {site_id}", rng.choice(REGIONS), installed_kw,
             peak_kw, commissioned.isoformat()]
        )
        for _ in range(rng.choice([1, 1, 2, 3])):
            inverter_seq += 1
            inverters.append(
                [f"INV-{inverter_seq:04d}", site_id, rng.choice(INVERTER_MODELS),
                 round(peak_kw / 2, 2)]
            )
        base_cf = 0.184
        for d in range(DAYS):
            reading_seq += 1
            day = START + timedelta(days=d)
            seasonal = 1.15 - 0.3 * d / DAYS
            cf = max(0.02, rng.gauss(base_cf * seasonal, 0.035))
            quality = rng.choices(["ok", "estimated", "missing"], [0.9, 0.07, 0.03])[0]
            energy = round(cf * peak_kw * 24, 2) if quality != "missing" else ""
            irradiance = round(cf * 30, 2) if quality == "ok" else ""
            readings.append(
                [f"R{reading_seq:06d}", site_id, day.isoformat(), energy, irradiance,
                 quality]
            )
    write(
        "raw_sites",
        ["site_id", "site_name", "region", "installed_kw", "peak_kw",
         "commissioned_on"],
        sites,
    )
    write("raw_inverters", ["inverter_id", "site_id", "inverter_model", "rated_kw"],
          inverters)
    write(
        "raw_generation_readings",
        ["reading_id", "site_id", "reading_date", "energy_kwh", "irradiance_kwh_m2",
         "reading_quality"],
        readings,
    )


if __name__ == "__main__":
    main()
