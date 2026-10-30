# Simulink twin

A Simulink model of the same battery and controller as the Python model. It runs the
same FCR test signals, and the same Python evaluator scores its output.

| File | Role |
| --- | --- |
| `fcr_controller_step.m`, `fcr_controller_init.m` | Controller as a pure step function with explicit state. Mirrors `nordic_bess.control` and `nordic_bess.sim.engine` (droop eq. 12/20-23, NEM/AEM eq. 14-19, limits eq. 24-26, Table 11) |
| `build_bess_fcr_twin.m` | Builds `bess_fcr_twin.slx` from scratch (MATLAB Function block, converter model, Simscape Electrical battery) |
| `run_twin.m` | Builds the model and simulates every exported test signal |
| `tests/TestFcrController.m` | `matlab.unittest` tests of the controller and the model |

## Model

A MATLAB Function block calls `fcr_controller_step` every 0.1 s. Its setpoint goes to an
average power-level converter model: saturation at P_max, a first-order lag (0.2 s), a
BMS clip at the energy limits, and charge and discharge efficiencies. The stored energy
is integrated from the DC power with the same accounting as the Python model.

On the DC side, a Simscape Electrical `Battery` block (1200 V, finite capacity) is fed by
a controlled current source with I = P_dc / V_dc. This adds battery voltage and charge to
the outputs. The AC side is not modelled: frequency is an input, as for a grid-following
unit.

## Workflow

```powershell
uv run python scripts/export_twin_inputs.py --config configs/base.yaml   # simulink/inputs/
matlab -batch "run('simulink/run_twin.m')"                                # simulink/outputs/
uv run python scripts/evaluate_twin.py --config configs/base.yaml         # docs/twin_report.md
matlab -batch "runtests('simulink/tests')"
```

Requires MATLAB R2025a with Simulink, Simscape and Simscape Electrical. The `inputs/` and
`outputs/` folders are regenerated and not committed. The comparison is in
`results/twin_comparison.csv` and [docs/twin_report.md](../docs/twin_report.md).
