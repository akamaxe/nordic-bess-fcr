# FCR specification notes

My working notes on *Technical Requirements for Frequency Containment Reserve Provision
in the Nordic Synchronous Area*, version 1.1 of 28 March 2025, in force from 2 June 2025
(joint document of Energinet, Fingrid, Statnett and Svenska kraftnät). The code cites
these section, table and equation numbers.

Official PDF:
https://www.svk.se/495d28/siteassets/aktorsportalen/bidra-med-reserver/om-olika-reserver/fcr/fcr-technical-requirements_v1.1_28_march_2025.pdf

The notes were checked against the PDF on 2026-10-30 (Tables 1, 3, 4, 6, 7, 10-13;
eq. 1-4, 7-12, 14-28). Where the document is ambiguous, the reading used here is stated
together with the PDF page. Sections 4 (measurement system), 6 (telemetry and data
logging) and 3.11-3.12 (aggregation) are not covered.

## 1. Products and steady-state activation (section 3, Table 1)

| Product | 100 % negative activation | 0 % activation | 100 % positive activation |
|---|---|---|---|
| FCR-D upwards | n/a | f >= 49.9 Hz | f <= 49.5 Hz |
| FCR-N | f >= 50.1 Hz | f = 50.0 Hz | f <= 49.9 Hz |
| FCR-D downwards | f >= 50.5 Hz | f <= 50.1 Hz | n/a |

- Activation is (close to) proportional to the frequency control error: dP = (1/e_p) * (f_ref - f) (eq. 12).
- One-sided frequency bands: **0.1 Hz for FCR-N, 0.4 Hz for FCR-D**.
- FCR-D may keep increasing linearly beyond 49.5 / 50.5 Hz. If the unit has no LFSM obligation,
  the FCR-D controller output may saturate at the sold volume (section 3.6.2).
- In steady state an entity providing FCR-N and FCR-D activates the **sum** of both (section 3.6.1).
  Recommended: separate controllers per product.
- Maximum provision per single point of failure: 70 MW per product and direction; 100 MW
  combined FCR-N + FCR-D per direction.
- FCR response must not be artificially delayed. FCR must be disabled when not procured.

## 2. FCR-N steady-state test (section 3.1.1, Table 3)

Step sequence on the frequency input:

| Step | Start [min] | Start, endurance test non-LER [min] | Duration [min] | Frequency [Hz] |
|---|---|---|---|---|
| 0 | 0 | 0 | 0.5 | 50.0 |
| pre-step | 0.5 | 0.5 | 0.5 | 49.95 |
| 0 | 1 | 1 | 5 | 50.0 |
| 1 | 6 | 6 | 5 / 15 | 49.9 |
| 2 | 11 | 21 | 5 / 15 | 50.1 |
| 3 | 16 | 36 | 5 | 50.0 |
| end | 21 | 41 | | |

(LER entities test endurance with the energy-management sequence in section 3.5.3 instead
of the 15-minute steps.)

Steady-state responses:
- dP_ss,1 = P_ss,1 - 0.5 * (P_ss,0 + P_ss,3)   (eq. 1)
- dP_ss,2 = P_ss,2 - 0.5 * (P_ss,0 + P_ss,3)   (eq. 2)

**Requirement 1 (FCR-N)**, with dP_th = theoretical steady-state response to 0.1 Hz:
- upwards: -0.05 <= (dP_ss,1 - |dP_th|) / |dP_th| <= 0.20
- downwards: -0.20 <= (dP_ss,2 + |dP_th|) / |dP_th| <= 0.05
- If not met, a reduction factor K_red,ss in [0.9, 1] may scale |dP_th|. Capacity
  C_FCR-N = min(K_red,ss, K_red,dyn) * |dP_th| (eq. 3). K_red < 0.9 -> fails prequalification.

## 3. FCR-D fast ramp test (section 3.1.2, Table 4)

| Ramp | Start [s] | End of ramp [s] | End of step [s] | Ramp speed [Hz/s] | Duration [s] | f FCR-D up [Hz] | f FCR-D down [Hz] | Purpose |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | - | 30 | 0 | 30 | 49.9 | 50.1 | wait for stable power |
| 1 | 30 | 33.1 | 34.9 | 0.14 | 4.9 | 49.45 | 50.55 | activation performance 1 |
| 2 | 34.9 | 39.9 | 90 | 0.09 | 55.1 | 49.9 | 50.1 | deactivation test 1 |
| 3 | 90 | 91.7 | 390 | 0.24 | 300 (900 endurance, non-LER) | 49.5 | 50.5 | steady state, full activation |
| 4 | 390 | 391.7 | 690 | 0.24 | >= 300 | 49.9 | 50.1 | steady state, zero activation |
| 5 | 690 | 693.8 | 750 | 0.24 | 60 | 49.0 | 51.0 | activation performance 2 |
| 6 | 750 | 754.2 | 1050 | 0.24 | >= 300 | 50.0 | 50.0 | deactivation test 2 |
| 7 | 1050 | 1050.8 | 1350 | 0.24 | 300 | 49.7 | 50.3 | FCR-N + FCR-D combination |
| 8 | 1350 | 1350.4 | 1650 | 0.24 | 300 | 49.89 | 50.11 | FCR-N + FCR-D combination |

Ramps 7-8 are only needed when the combination of FCR-N and FCR-D is tested.
Generate the signal from start frequency, ramp speed and target (the "end of ramp" column
is then only a cross-check). Resolved against PDF p. 16: the table values above are exactly
those in the PDF, but the PDF's own "end of ramp" column disagrees with start + |df| / speed
for ramp 1 (33.21 s computed vs 33.1 s), ramp 7 (1051.25 s vs 1050.8 s) and ramp 8
(1350.79 s vs 1350.4 s). Ramps 0 and 2-6 agree to the printed precision. The generator uses
speed and target, and a test asserts this documented mismatch.

**Requirement 1b (combination FCR-N + FCR-D, ramps 6-7 and 6-8, PDF p. 20)**, upwards:

-0.05 <= ((P_ss,x - P_ss,6) - |dP_N,th| - (|df_x| - 0.1) |dP_Dup,th| / 0.4)
         / (|dP_N,th| + (|df_x| - 0.1) |dP_Dup,th| / 0.4) <= 0.20

and the mirrored form for downwards (-0.20 ... 0.05, with + signs). P_ss,x is the steady
state after ramp 7 or 8, df_x the frequency change from the end of ramp 6 to the end of
ramp 7 or 8, taken as a magnitude (0.3 Hz for ramp 7 gives half FCR-D activation; 0.11 Hz for
ramp 8 gives 2.5 %). The PDF prints the FCR-D factor as |df_x - 0.1| / 0.4. Only relevant
when FCR-N and FCR-D are tested together.

dP_th for FCR-D = theoretical steady-state response from 49.9 -> 49.5 Hz (up) or
50.1 -> 50.5 Hz (down).

**Requirement 1 (FCR-D)**, from ramps 3 and 4:
- up: -0.05 <= (P_ss,3 - P_ss,4 - |dP_th|) / |dP_th| <= 0.20
- down: -0.20 <= (P_ss,3 - P_ss,4 + |dP_th|) / |dP_th| <= 0.05

**Requirement 2** (ramp 5): |dP(7.5 s)| >= 0.86 * |dP_th|, where dP(7.5 s) is the activated
power 7.5 s after the start of the ramp.

**Requirement 3** (ramp 5): |E(7.5 s)| >= 3.2 s * |dP_th|, with E(7.5 s) = integral of dP(t)
from ramp start to ramp start + 7.5 s (eq. 4), in MWs.

After 7.5 s the activated power must not drop below dP(7.5 s) until the start of ramp 6
(small well-damped oscillations accepted).

**Requirement 4** (deactivation, ramps 1-2): nadir (zenith for FCR-D down) assumed at
**4.4 s after the start of ramp 1**. For k from t_nadir to t_nadir + 40 s:

max_k integral_{t_nadir}^{k} ( dP(t) - min(|dP_nadir|, 0.5 * |dP_th|) ) dt <= 2.5 s * |dP_th|

(FCR-D down: use -dP(t) and the zenith.)

Reduction factors for FCR-D: K_red in [0.75, 1] (TSO may allow down to 0.5 on request).
Requirement 2 and 3 with K_red,dyn multiply the right-hand side by K_red,dyn.
Mode shifting (high-performance / high-stability modes) is allowed with rules in section
3.1.2 (activation at <= 49.8 / >= 50.2 Hz, deactivate within 10 s, block 5-15 min).
A BESS normally does not need it: out of scope unless required.

## 4. Sine tests: stability and performance (sections 3.2-3.3, Tables 6-7)

Test signal: 50 Hz nominal plus a sinusoid. Amplitude +/-100 mHz.
- FCR-N: centred at 50.0 Hz, FCR-D inactive, most challenging loading, **high droop**.
- FCR-D up: centred at 49.7 Hz; FCR-D down: centred at 50.3 Hz; FCR-N inactive, **low droop**.
  If FCR-D up and down share parameters, one of them is enough.

| Period T [s] | Stationary periods (recommended total) | FCR-N | FCR-D |
|---|---|---|---|
| 10 | 5 (20) | x | x |
| 15 | 5 (15) | x | x |
| 25 | 5 (10) | x | x |
| 40 | 5 (7) | x | x |
| 50 | 5 (7) | x | x |
| 60 | 5 (7) | x | x |
| 70 | 5 (7) | x | x |
| 90 | 5 (7) | x | (only high-stability mode) |
| 150 | 3 (4) | x | (only high-stability mode) |
| 300 | 2 (3) | x | (only high-stability mode) |

From 2-5 stationary periods per test, fit amplitude and phase:
- |F(jw)| = (A_P(w) / A_f(w)) * (|df_X| / |dP_X,th|)   (eq. 7), df_X = 0.1 Hz (N) or 0.4 Hz (D)
- phi = (t_peak,f - t_peak,P) * 360 deg / T   (eq. 8), negative when power lags.
- F(jw) = |F| cos(phi) + j |F| sin(phi)   (eq. 9)
- If the test signal is injected inside the controller, multiply by the frequency
  measurement equipment transfer function F_FME(jw) (section 4.4).

Power system model (eq. 11), form confirmed against PDF p. 27:

G(jw) = (dP_X / df_X) * (f0 / S_n) * 1 / (2 H jw + K_f * f0)   [p.u.]

Table 7 parameters:

| Parameter | FCR-N performance | FCR-N stability | FCR-D performance | FCR-D stability |
|---|---|---|---|---|
| dP_X [MW] | 600 | 600 | 1450 | 1450 |
| df_X [Hz] | 0.1 | 0.1 | 0.4 | 0.4 |
| f0 [Hz] | 50 | 50 | 50 | 50 |
| S_n [MW] | 42 000 | 23 000 | 42 000 | 23 000 |
| H [s] | 190 000 MWs / S_n = 4.5238 | 120 000 MWs / S_n = 5.2174 | 4.5238 | 5.2174 |
| K_f [p.u./Hz] | 0.01 | 0.01 | 0.01 | 0.01 |

**Requirement 8 (stability):** the Nyquist curve of the open loop G0(jw) (interpolated
between measured points) must pass to the right of, and outside, a circle of radius **0.43**
around (-1, 0j). A 95 % margin is accepted (stay outside radius 0.43 * 0.95). Computed
separately for FCR-N, FCR-D up and FCR-D down with the *stability* parameters.
**Sign convention (resolved, PDF p. 27-29):** eq. 10 writes G0 = F * G and the Requirement 8
box writes G0 = -F * G. We use **G0 = F * G**. F (eq. 7-9) is defined from the frequency
control error (f_ref - f) to power, so an ideal proportional unit has F = 1 and the loop
gain is F * G, consistent with the 1 + F G denominator of Requirement 9. With G0 = F * G an
ideal unit gives a curve in the right half plane and a lagging unit enters the third
quadrant near (-1, 0j) at short periods, which is what Figure 10 shows. With -F * G the
ideal unit would sit at about -26 at low frequency and encircle (-1, 0j). The minus sign in
the box corresponds to defining F from the frequency deviation (f - f0) instead.
FCR-N exemption to a 75 % margin is possible on request (not modelled).

**Requirement 9 (performance):** with the *performance* parameters and disturbance profile
D(s) = 1 / (70 s + 1):

K_margin * | G_perf(s) / (1 + F(s) G_perf(s)) | < | 1 / D(s) |, K_margin = 0.95

If not met, K_red,dyn may be applied (F(s) / K_red,dyn), not below 0.9 (FCR-N) or 0.75 (FCR-D).

## 5. Linearity (section 3.4)

**Requirement 10 (dynamic linearity, from the sine tests):** for each period, fit a sine with
the test period by least squares to the baseline-free power P_mv, giving P_est. Then

sqrt( sum (P_mv - P_est)^2 ) / sqrt( sum (P_est - mean(P_est))^2 ) < 1

Static/non-continuous linearity tests (section 3.4.2, Requirement 11) apply to relay-switched
or static FCR-D resources only: out of scope for a continuously controlled BESS.

## 6. Limited energy reservoirs (LER) (section 3.5)

An entity is LER if its usable energy is smaller than **2 hours** of continuous full
activation of the prequalified FCR capacity. LER entities must implement NEM and AEM and
reserve power and energy as follows (Table 10, C = sold capacity in MW):

| | FCR-N | FCR-D upwards | FCR-D downwards |
|---|---|---|---|
| Required power upwards [MW] | +1.34 C_N | +C_Dup | +0.20 C_Ddown |
| Required power downwards [MW] | -1.34 C_N | -0.20 C_Dup | -C_Ddown |
| Required energy upwards [MWh] | 1 h * C_N | (1/3) h * C_Dup | 0 |
| Required energy downwards [MWh] | 1 h * C_N | 0 | (1/3) h * C_Ddown |

When several products are provided simultaneously, **sum the columns**. FCR-N activation
must never deplete the energy reserved for FCR-D.

Endurance: FCR-N >= 60 min in both directions. FCR-D: 15 min of full activation in alert
state, 20 min in total. Suggested starting SOC: about 50 % for symmetric products, near
0 % or 100 % for asymmetric ones. FCR-N delivery periods are currently 1-hour increments.
The TSOs note that Table 10 and Table 11 will be re-evaluated (FCR-N energy foreseen in
1-1.5 h per direction): keep them as configuration.

### 6.1 Normal State Energy Management, NEM (section 3.5.1)

- NEM may shift the baseline (setpoint) to restore SOC, **only while 49.9 < f < 50.1 Hz**.
  Outside the normal band NEM ramps back to zero.
- SOC = E_actual / E_max, using only the energy range used for FCR provision.
- NEM_allowed(t) = -1 if 49.9 < f < 50.1 and SOC < lower threshold;
  +1 if 49.9 < f < 50.1 and SOC > upper threshold; 0 otherwise   (eq. 14)
  (enable/disable thresholds give hysteresis, Table 11.)
- NEM_current(t_i) = mean of NEM_allowed over the last 300 s at 1 s resolution   (eq. 15)
- FCR-N: P_tot = P_FCR-N + 0.34 * C_N * NEM_current   (eq. 16), rate may be raised up to 0.50 * C_N.
- FCR-D: P_tot = P_FCR-D + 0.20 * C_D * NEM_current   (eq. 17), rate may be raised up to 0.34 * C_D.
  Depleted FCR-D reservoirs must be restored within 120 min.
- FCR-D NEM thresholds have no hysteresis in v1.1: enable and disable are both at 20 minutes
  of remaining endurance (PDF p. 40, Table 11 p. 41). FCR-N uses 30 min (enable) and
  57.5 min (disable).

### 6.2 Alert State Energy Management, AEM (section 3.5.2)

- AEM controls a smooth exhaustion when the reservoir is nearly empty or full. While AEM is
  active the entity is considered **not available** (endurance reported as 0).
- f_ref,X(t) = mean of f_AEM,X over the last 300 s at 1 s resolution   (eq. 18)
- f_AEM,X = f0,X if AEM not active; f_meas,X(t) if AEM active   (eq. 19)
  with f0 = 50.0 Hz (N), 49.9 Hz (D up), 50.1 Hz (D down).
- Saturations (eq. 20-22): N: clip(f, 49.9, 50.1); D up: min(f, 49.9); D down: max(f, 50.1).
- P_X(t) = (C_X / df_max) * (f_ref,X - f_meas,X(t))   (eq. 23), df_max = 0.1 Hz (N), 0.4 Hz (D).
- Output limits (eq. 24-26): FCR-N within +/-(C_N + P_NEM,max,N); FCR-D up not below
  -P_NEM,max,Dup; FCR-D down not above +P_NEM,max,Ddown.

### 6.3 SOC thresholds (Table 11)

E = energy range available for FCR provision [MWh], C in MW, times in hours.

| Threshold | FCR-N | FCR-D up | FCR-D down |
|---|---|---|---|
| enable AEM, upper | 1 - C_N (5/60) / E | n/a | 1 - C_D (5/60) / E |
| disable AEM, upper | 1 - C_N (10/60) / E | n/a | 1 - C_D (10/60) / E |
| enable NEM, upper | 1 - C_N (30/60) / E | n/a | 1 - C_D (20/60) / E |
| disable NEM, upper (*) | 1 - C_N (57.5/60) / E | n/a | 1 - C_D (20/60) / E |
| disable NEM, lower (*) | C_N (57.5/60) / E | C_D (20/60) / E | n/a |
| enable NEM, lower | C_N (30/60) / E | C_D (20/60) / E | n/a |
| disable AEM, lower | C_N (10/60) / E | C_D (10/60) / E | n/a |
| enable AEM, lower | C_N (5/60) / E | C_D (5/60) / E | n/a |

(*) For reservoirs larger than the minimum, the disable thresholds must be moved so that the
nominal SOC can be restored, with NEM smoothly disabled over 5 minutes near that level.
Implement all thresholds as configurable parameters.

### 6.4 Endurance (section 3.5.4, eq. 27-28), in minutes

- L_up = | (E_current - E_min) / (P_setpoint + C_up - P_inflow) | * 60
- L_down = | (E_max - E_current) / (P_inflow - P_setpoint + C_down) | * 60
- FCR-N endurance = min(L_up, L_down); FCR-D up uses L_up; FCR-D down uses L_down.
- In AEM, report 0 in that direction.

### 6.5 Energy management test sequences (section 3.5.3)

Durations are examples; hold each step until the stated condition is met.

FCR-N (Table 12):

| Step | Start [min] | Min. duration [min] | f [Hz] | NEM | AEM | Condition |
|---|---|---|---|---|---|---|
| 0 | 0 | 2 | 50.0 | off | off | |
| 1 | 2 | 28 | 50.09 | on | off | hold until NEM fully active >= 1 min |
| 2 | 30 | 6 | 50.11 | off | off | NEM off when f > 50.1 |
| 3 | 36 | 2.5 | 50.09 | on | off | NEM back on |
| 4 | 38.5 | 7.5 | 50.11 | off | on | hold 5 min after AEM on (high SOC) |
| 5 | 46 | 10 | 50.09 | on | on | |
| 6 | 56 | 60 | 49.91 | off -> on | off | until NEM/AEM off, then NEM fully active >= 1 min (low SOC) |
| 7 | 116 | 5 | 49.89 | off | off | NEM off when f < 49.9 |
| 8 | 121 | 2.5 | 49.91 | on | off | |
| 9 | 123.5 | 10 | 49.89 | off | on | hold 5 min after AEM on (low SOC) |
| 10 | 133.5 | 10 | 49.91 | on | on | |
| 11 | 143.5 | 30 | 50.0 | off | off | until NEM and AEM off |

PDF example (Figure 20): simulated 1.34 MW / 2 MWh battery, C_N = 1 MW, 2 MWh reserved for
FCR-N, initial SOC 62.5 %
(useful as a regression test).

FCR-D up / down (Table 13):

| Step | Start [min] | Min. duration [min] | f up [Hz] | f down [Hz] | NEM | AEM | Condition |
|---|---|---|---|---|---|---|---|
| 0 | 0 | 0.5 | 49.91 | 50.09 | off | off | |
| 1 | 0.5 | 10 | 49.5 | 50.5 | off | off | hold until NEM turns on in step 2 |
| 2 | 10.5 | 2.5 | 49.91 | 50.09 | on | off | NEM on when back in normal band |
| 3 | 13 | 15 | 49.5 | 50.5 | off | on | hold 5 min after AEM on |
| 4 | 28 | 15 | 49.91 | 50.09 | on -> off | off | until NEM and AEM off |

PDF example (Figure 21, FCR-D down): "simulated 3 MW / 1 MWh battery, FCR-D capacity 3 MW,
energy reserved for FCR-D 3 MWh", initial SOC 0 %. The caption is internally inconsistent
(1 MWh vs 3 MWh); not used as a regression target.

Table 12 step 6 and Table 13 step 4 list two NEM states in one cell (NEM off then on, or on
then off, as the SOC crosses thresholds during the step); AEM is off at the end of both.

**Requirement 12 (LER):** the response stays activated as long as the deviation persists,
and NEM/AEM behave as specified in sections 3.5.1-3.5.2.

## 7. Start and end of provision (section 3.7)

- FCR-N start: step the controller frequency input from 50.0 Hz to the measured frequency;
  end: step back to 50.0 Hz and stop once the response has ceased.
- FCR-D end with an ongoing response: keep providing until the frequency is back in the
  normal band; if the deviation lasts, ramp down starting 15 min after the scheduled end,
  over 5 min.
- When sold volumes change between market time units during a disturbance, follow the bid
  of the second market time unit.

## 8. Prequalification process facts (section 2)

- Test results in an application must be less than 1 year old.
- Prequalification is valid 5 years; reassessment also after equipment changes.
- The TSOs provide an IT tool that evaluates test results and a tuning guideline (see
  Svenska kraftnät's prequalification page). Comparing this evaluator with that tool is
  still to do.
