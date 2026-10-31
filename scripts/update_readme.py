"""Fill the result blocks of README.md from results/*.csv.

Every number in these blocks comes from a CSV written by the pipeline scripts.
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


def revenue_table(df: pd.DataFrame, p_max_mw: float) -> str:
    scale = 1e3 * p_max_mw * df["hours"] / 8760.0
    lines = [
        "| Strategy | Day-ahead | FCR-N | FCR-D up | FCR-D down | Degradation | Net | "
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
            f"| {r['strategy']} {r['description']} | {cells} | {vals[-1]:.1f} | "
            f"{r['cycles_per_year']:.0f} |"
        )
    caption = "kEUR per MW-year, SE3, 2025. Net is the sum of the other columns."
    return "\n".join(lines) + "\n\n" + caption


def compliance_summary(df: pd.DataFrame) -> str:
    """One paragraph with the verdict; the full table is in docs/compliance_report.md."""
    n_pass, n = int(df["passed"].sum()), len(df)
    reqs = sorted({int(x) for x in df["requirement"].str.extract(r"R(\d+)")[0]})
    req_list = ", ".join(str(r) for r in reqs[:-1]) + f" and {reqs[-1]}"
    if n_pass == n:
        verdict = f"All {n} checks pass"
    else:
        failed = ", ".join(f"{r.requirement} {r.product}" for r in df[~df["passed"]].itertuples())
        verdict = f"{n_pass} of {n} checks pass (failed: {failed})"
    return (
        f"{verdict}. They cover Requirements {req_list}, each for the products it applies "
        "to. The measured value and limit of every check, and a figure for every test, are "
        "in [docs/compliance_report.md](docs/compliance_report.md)."
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


def market_cases_table(df: pd.DataFrame) -> str:
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


def spaced_separators(text: str) -> str:
    """Write table separator rows as '| --- | ---: |' (markdownlint MD060)."""

    def fix(m: re.Match) -> str:
        cells = [c.strip() for c in m.group(0).strip().strip("|").split("|")]
        return "| " + " | ".join(cells) + " |"

    return re.sub(r"^\|(?:\s*:?-{3,}:?\s*\|)+\s*$", fix, text, flags=re.M)


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
        "compliance": (res / "compliance_results.csv", compliance_summary),
        "simulation": (res / "simulation_kpis.csv", lambda d: simulation_table(d.iloc[0])),
        "market_cases": (res / "market_cases.csv", market_cases_table),
    }
    for name, (path, render) in blocks.items():
        if path.exists() and f"<!-- BEGIN {name} -->" in text:
            text = replace_block(text, name, render(pd.read_csv(path)))
            print(f"updated block {name} from {path.name}")
    readme.write_text(spaced_separators(text), encoding="utf-8")


if __name__ == "__main__":
    main()
