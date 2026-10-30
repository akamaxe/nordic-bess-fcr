"""Score the Simulink digital twin with the Python evaluator (PLAN M5).

Reads simulink/outputs/<signal>.csv written by simulink/run_twin.m, runs the same test
signals through the Python BESS model and evaluates both with
nordic_bess.compliance.evaluate. Acceptance (PLAN M5): on the FCR-D ramp tests the
activated power differs by an RMSE below 2 % of the tested capacity, and both models
give identical pass/fail. Writes results/twin_comparison.csv,
results/twin_requirements.csv, docs/twin_report.md and docs/figures/twin_*.png.
Exits with status 1 if the acceptance fails.

Usage: uv run python scripts/evaluate_twin.py --config configs/base.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from nordic_bess.compliance.evaluate import evaluate_fcr_d_ramp, evaluate_r1_fcr_n
from nordic_bess.compliance.report import results_markdown
from nordic_bess.compliance.runner import activated_power, simulate_signal, tested_capacity
from nordic_bess.compliance.signals import fcr_d_ramp_sequence, fcr_n_step_sequence
from nordic_bess.config import load_config
from nordic_bess.plant.battery import BatteryParams
from nordic_bess.reporting.style import AQUA, DPI, INK, MAGENTA, new_figure
from nordic_bess.spec import Product

SIGNALS = {
    "fcr_n_step": lambda dt: fcr_n_step_sequence(dt),
    "fcr_d_up_ramp": lambda dt: fcr_d_ramp_sequence(Product.FCR_D_UP, dt),
    "fcr_d_down_ramp": lambda dt: fcr_d_ramp_sequence(Product.FCR_D_DOWN, dt),
}


def simulink_activated(path: Path, t_grid: np.ndarray, dt: float) -> np.ndarray:
    """Simulink activated power on the Python grid.

    Simulink logs the continuous output at t_k; the Python engine stores in step i the
    output at the end of the step, so Python sample i matches Simulink at t_i + dt.
    """
    sl = pd.read_csv(path)
    nem = sl[["p_nem_n_mw", "p_nem_dup_mw", "p_nem_ddown_mw"]].sum(axis=1)
    p = (sl["p_out_mw"] - nem).to_numpy()
    return np.interp(t_grid + dt, sl["t_s"].to_numpy(), p)


def overlay_figure(sig, p_py, p_sl, c_mw):
    fig, (ax, ax_z) = new_figure(10.0, 3.8, ncols=2, width_ratios=(1.6, 1))
    ax.plot(sig.t_s, p_py, color=AQUA, linewidth=1.6, label="Python model")
    ax.plot(sig.t_s, p_sl, color=MAGENTA, linewidth=1.0, linestyle="--", label="Simulink twin")
    ax.set_xlabel("Time [s]")
    ax.set_ylabel("Activated power [MW]")
    ax.set_title("FCR-D up ramp test: Python model and Simulink twin", loc="left")
    ax.legend(loc="upper right")
    t0 = sig.segment("ramp5").t_start_s
    mask = (sig.t_s >= t0 - 1) & (sig.t_s <= t0 + 6)
    ax_z.plot(sig.t_s[mask] - t0, p_py[mask], color=AQUA, linewidth=1.6)
    ax_z.plot(sig.t_s[mask] - t0, p_sl[mask], color=MAGENTA, linewidth=1.0, linestyle="--")
    ax_z.axhline(c_mw, color=INK, linewidth=0.6)
    ax_z.set_xlabel("Time after the start of ramp 5 [s]")
    ax_z.set_title("Ramp 5 detail", loc="left")
    fig.tight_layout()
    return fig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--twin-dir", default="simulink")
    args = parser.parse_args()
    cfg = load_config(args.config)
    twin = Path(args.twin_dir)
    manifest = json.loads((twin / "inputs" / "manifest.json").read_text(encoding="utf-8"))
    dt = cfg.simulation.test_signal_step_s
    window = cfg.compliance.steady_state_window_s
    battery = BatteryParams.from_config(cfg)

    rows, req_rows, sl_results, ok = [], [], [], True
    for item in manifest:
        sig = SIGNALS[item["name"]](dt)
        c = tested_capacity(cfg, sig.product)
        p_py = activated_power(simulate_signal(cfg, sig, battery))
        p_sl = simulink_activated(twin / "outputs" / f"{item['name']}.csv", sig.t_s, dt)
        if sig.product is Product.FCR_N:
            res_py = evaluate_r1_fcr_n(sig, p_py, c, window)
            res_sl = evaluate_r1_fcr_n(sig, p_sl, c, window)
        else:
            res_py = evaluate_fcr_d_ramp(sig, p_py, c, window)
            res_sl = evaluate_fcr_d_ramp(sig, p_sl, c, window)
        sl_results += res_sl
        err = p_sl - p_py
        rmse = float(np.sqrt(np.mean(err**2)))
        identical = all(a.passed == b.passed for a, b in zip(res_py, res_sl, strict=True))
        accepted = identical and (
            sig.product is Product.FCR_N or rmse < cfg.twin.rmse_tolerance_share * c
        )
        ok &= accepted
        rows.append(
            {
                "signal": item["name"],
                "product": sig.product.value,
                "c_mw": c,
                "rmse_mw": rmse,
                "rmse_share_of_c": rmse / c,
                "max_abs_error_mw": float(np.max(np.abs(err))),
                "identical_pass_fail": identical,
                "accepted": accepted,
            }
        )
        for a, b in zip(res_py, res_sl, strict=True):
            req_rows.append(
                {
                    "signal": item["name"],
                    "requirement": a.requirement,
                    "product": a.product,
                    "measured_python": a.measured,
                    "measured_simulink": b.measured,
                    "passed_python": a.passed,
                    "passed_simulink": b.passed,
                }
            )
        if item["name"] == "fcr_d_up_ramp":
            fig = overlay_figure(sig, p_py, p_sl, c)
            fig.savefig(cfg.paths.figures / "twin_fcr_d_up_ramp.png", dpi=DPI)
            plt.close(fig)

    comp = pd.DataFrame(rows)
    reqs = pd.DataFrame(req_rows)
    comp.round(6).to_csv(cfg.paths.results / "twin_comparison.csv", index=False)
    reqs.round(6).to_csv(cfg.paths.results / "twin_requirements.csv", index=False)
    lines = [
        "# Digital twin report",
        "",
        "Generated by `scripts/evaluate_twin.py`. The Simulink model "
        "(`simulink/bess_fcr_twin.slx`, built by `simulink/build_bess_fcr_twin.m`) runs the "
        "test signals exported by `scripts/export_twin_inputs.py`; its output is scored by "
        "the same Python evaluator as the Python BESS model.",
        "",
        "## Python model versus Simulink twin",
        "",
        "| Signal | Product | C [MW] | RMSE [MW] | RMSE / C | Max error [MW] | Same pass/fail |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['signal']} | {r['product']} | {r['c_mw']:g} | {r['rmse_mw']:.2e} | "
            f"{100 * r['rmse_share_of_c']:.1e} % | {r['max_abs_error_mw']:.2e} | "
            f"{'yes' if r['identical_pass_fail'] else 'NO'} |"
        )
    lines += [
        "",
        f"Acceptance (PLAN M5): RMSE below {100 * cfg.twin.rmse_tolerance_share:g} % of C on "
        f"the FCR-D ramp tests and identical pass/fail: **{'met' if ok else 'NOT met'}**.",
        "",
        "## Requirements evaluated on the Simulink output",
        "",
        results_markdown(sl_results),
        "",
        "![Python versus Simulink](figures/twin_fcr_d_up_ramp.png)",
        "",
    ]
    (cfg.paths.figures.parent / "twin_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(comp.to_string(index=False))
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
