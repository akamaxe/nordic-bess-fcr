"""Fill the result tables of README.md from results/*.csv (PLAN M6).

Every number in the README tables comes from a CSV written by the pipeline scripts.
Blocks between ``<!-- BEGIN name -->`` and ``<!-- END name -->`` are replaced; a block
whose CSV is missing is left untouched.

Usage: uv run python scripts/update_readme.py --config configs/base.yaml
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

from nordic_bess.config import load_config

PRODUCTS = ("FCR-N", "FCR-D up", "FCR-D down")


def revenue_table(df: pd.DataFrame, p_max_mw: float) -> str:
    scale = 1e3 * p_max_mw * df["hours"] / 8760.0
    lines = [
        "| Strategy | Day-ahead | FCR-N | FCR-D up | FCR-D down | Degradation | **Net** | "
        "Cycles / yr |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, r in df.iterrows():
        vals = [
            r[c] / scale[i]
            for c in (
                "rev_da_eur",
                "rev_fcr_n_eur",
                "rev_fcr_dup_eur",
                "rev_fcr_ddown_eur",
                "cost_degradation_eur",
                "net_eur",
            )
        ]
        cells = " | ".join(f"{v:.1f}" for v in vals[:-1])
        lines.append(
            f"| {r['strategy']} {r['description']} | {cells} | **{vals[-1]:.1f}** | "
            f"{r['cycles_per_year']:.0f} |"
        )
    return "\n".join(lines) + "\n\nkEUR per MW-year (net = sum of the streams), SE3, 2025."


def compliance_table(df: pd.DataFrame) -> str:
    reqs = list(dict.fromkeys(df["requirement"]))
    lines = ["| Requirement | " + " | ".join(PRODUCTS) + " |", "|---|---|---|---|"]
    for req in reqs:
        cells = []
        for prod in PRODUCTS:
            row = df[(df["requirement"] == req) & (df["product"] == prod)]
            if row.empty:
                cells.append("-")
                continue
            r = row.iloc[0]
            mark = "PASS" if r["passed"] else "**FAIL**"
            unit = " s" if r["unit"] == "s" else ""
            value = f"{r['measured']:.0f}" if r["unit"] == "steps" else f"{r['measured']:.2f}"
            cells.append(f"{mark} ({value}{unit}; {r['threshold']})")
        lines.append(f"| {req} | " + " | ".join(cells) + " |")
    n_pass, n = int(df["passed"].sum()), len(df)
    return (
        "\n".join(lines) + f"\n\n**{n_pass} of {n} checks pass.** Details and figures: "
        "[docs/compliance_report.md](docs/compliance_report.md)."
    )


def simulation_table(k: pd.Series) -> str:
    rows = [
        ("Simulated period", f"{k['duration_h'] / 24:.0f} days at 1 s, schedule {k['strategy']}"),
        ("FCR unavailable", f"{k['unavailable_minutes']:.1f} min"),
        ("Time with NEM active (FCR-N)", f"{100 * k['nem_share_n']:.1f} %"),
        (
            "Minimum endurance FCR-N / FCR-D up / FCR-D down",
            f"{k['endurance_n_min_minutes']:.0f} / {k['endurance_dup_min_minutes']:.0f} / "
            f"{k['endurance_ddown_min_minutes']:.0f} min",
        ),
        ("Energy at start / end", f"{k['e_start_mwh']:.1f} / {k['e_end_mwh']:.1f} MWh"),
        (
            "Day-ahead delivery shortfall (BMS limit)",
            f"{k['energy_shortfall_mwh']:.1f} MWh in {k['energy_limited_minutes']:.0f} min",
        ),
        ("Equivalent full cycles", f"{k['equivalent_cycles']:.1f}"),
        ("Energy balance error", f"{k['energy_balance_error_mwh']:.1e} MWh"),
    ]
    return "| KPI | Value |\n|---|---|\n" + "\n".join(f"| {a} | {b} |" for a, b in rows)


def m2b_table(df: pd.DataFrame) -> str:
    lines = [
        "| Case | Net kEUR / MW-yr | Change vs reference | Cycles / yr |",
        "|---|---:|---:|---:|",
    ]
    for _, r in df.iterrows():
        delta = r["delta_vs_reference_eur_per_mw_year"] / 1e3
        change = "reference" if abs(delta) < 1e-9 else f"{delta:+.1f}"
        lines.append(
            f"| {r['case']} | {r['eur_per_mw_year'] / 1e3:.1f} | {change} | "
            f"{r['cycles_per_year']:.0f} |"
        )
    return "\n".join(lines)


def replace_block(text: str, name: str, body: str) -> str:
    pattern = re.compile(rf"(<!-- BEGIN {name} -->\n).*?(<!-- END {name} -->)", re.S)
    if not pattern.search(text):
        raise SystemExit(f"README has no block {name!r}")
    return pattern.sub(lambda m: m.group(1) + body + "\n" + m.group(2), text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--readme", default="README.md")
    args = parser.parse_args()
    cfg = load_config(args.config)
    res = cfg.paths.results
    readme = Path(args.readme)
    text = readme.read_text(encoding="utf-8")
    blocks = {
        "revenue": (res / "revenue_summary.csv", lambda d: revenue_table(d, cfg.bess.p_max_mw)),
        "compliance": (res / "compliance_results.csv", compliance_table),
        "simulation": (res / "simulation_kpis.csv", lambda d: simulation_table(d.iloc[0])),
        "m2b": (res / "m2b_summary.csv", m2b_table),
    }
    for name, (path, render) in blocks.items():
        if path.exists() and f"<!-- BEGIN {name} -->" in text:
            text = replace_block(text, name, render(pd.read_csv(path)))
            print(f"updated block {name} from {path.name}")
    readme.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
