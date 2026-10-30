# Simulink digital twin (M5)

A Simulink model of the same battery and controller as the Python model, driven by the
same FCR test signals and scored by the same Python evaluator.

| File | Role |
|---|---|
| `fcr_controller_step.m`, `fcr_controller_init.m` | Controller as a pure step function with explicit state; mirrors `nordic_bess.control` and `nordic_bess.sim.engine` (droop eq. 12/20-23, NEM/AEM eq. 14-19, limits eq. 24-26, Table 11) |
| `build_bess_fcr_twin.m` | Builds `bess_fcr_twin.slx` from scratch (MATLAB Function block, converter model, Simscape Electrical battery) |
| `run_twin.m` | Builds the model and simulates every exported test signal |
| `tests/TestFcrController.m` | `matlab.unittest` tests of the controller and the model |

## Model

- **Controller:** a MATLAB Function block calls `fcr_controller_step` every 0.1 s.
- **Converter:** an average power-level model: setpoint saturation at P_max, first-order
  lag (0.2 s), a BMS clip at the energy limits, and charge and discharge efficiencies.
- **Storage:** the stored energy is integrated from the DC power, with the same accounting
  as the Python model.
- **DC network (Simscape Electrical):** a `Battery` block (1200 V, finite capacity) is
  fed by a controlled current source, I = P_dc / V_dc. It adds battery voltage and
  charge to the outputs.
- **AC side:** not modelled. The frequency is an input, as for a grid-following unit.

## Workflow

```powershell
uv run python scripts/export_twin_inputs.py --config configs/base.yaml   # simulink/inputs/
matlab -batch "run('simulink/run_twin.m')"                                # simulink/outputs/
uv run python scripts/evaluate_twin.py --config configs/base.yaml         # docs/twin_report.md
matlab -batch "runtests('simulink/tests')"
```

Requires MATLAB R2025a with Simulink, Simscape and Simscape Electrical. The inputs and
outputs folders are regenerated and not committed; the comparison is in
`results/twin_comparison.csv` and [docs/twin_report.md](../docs/twin_report.md).
