"""Run the FCR prequalification tests on the BESS model and write the report (PLAN M4).

Writes docs/compliance_report.md, results/compliance_results.csv and the compliance
figures in docs/figures/. Exits with status 1 if any requirement fails.

Usage: uv run python scripts/run_compliance.py --config configs/base.yaml
"""

from __future__ import annotations

import argparse
import sys

import matplotlib.pyplot as plt

from nordic_bess.compliance.report import write_report
from nordic_bess.compliance.runner import results_table, run_bess_compliance, tested_capacity
from nordic_bess.config import load_config
from nordic_bess.reporting import compliance_plots as cp
from nordic_bess.reporting.style import DPI
from nordic_bess.spec import Product

SLUG = {Product.FCR_N: "fcr_n", Product.FCR_D_UP: "fcr_d_up", Product.FCR_D_DOWN: "fcr_d_down"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="configs/base.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)
    run = run_bess_compliance(cfg)

    figs_dir = cfg.paths.figures
    figs_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.results.mkdir(parents=True, exist_ok=True)
    figures = {}

    def save(fig, name: str, caption: str) -> None:
        fig.savefig(figs_dir / name, dpi=DPI)
        plt.close(fig)
        figures[caption] = f"figures/{name}"

    sig, df = run.traces["fcr_n_step"]
    save(
        cp.fcr_n_step(sig, df, cfg.compliance.c_fcr_n_mw),
        "compliance_fcr_n_step.png",
        "FCR-N step response",
    )
    for key, product in (
        ("fcr_d_up_ramp", Product.FCR_D_UP),
        ("fcr_d_down_ramp", Product.FCR_D_DOWN),
    ):
        sig, df = run.traces[key]
        save(
            cp.fcr_d_ramp(sig, df, tested_capacity(cfg, product)),
            f"compliance_{key}.png",
            f"{cp.PRODUCT_LABELS[product]} ramp response with the 7.5 s requirements",
        )
    save(cp.nyquist(run.transfer), "compliance_nyquist.png", "Nyquist stability (Requirement 8)")
    save(
        cp.closed_loop(run.transfer),
        "compliance_closed_loop.png",
        "Closed-loop performance (Requirement 9)",
    )
    for product, ler in run.ler.items():
        name = f"compliance_ler_{SLUG[product]}.png"
        save(
            cp.ler_test(ler, tested_capacity(cfg, product)),
            name,
            f"{cp.PRODUCT_LABELS[product]} LER energy-management test (Requirement 12)",
        )

    table = results_table(run.results)
    table.to_csv(cfg.paths.results / "compliance_results.csv", index=False)
    report = write_report(cfg, run.results, figures)
    (figs_dir.parent / "compliance_report.md").write_text(report, encoding="utf-8")

    view = table[["requirement", "product", "measured", "threshold", "passed"]]
    print(view.round(3).to_string(index=False))
    print(f"{int(table['passed'].sum())}/{len(table)} checks pass")
    if not table["passed"].all():
        sys.exit(1)


if __name__ == "__main__":
    main()
