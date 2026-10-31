# Assumptions and limitations

These are the modelling choices behind the results in the [README](../README.md), grouped
by part of the model. Where the FCR requirements leave room for interpretation, the item
says how I read them.

## Market

- Price taker. The reference case has perfect foresight, so its revenue is an upper
  bound. The forecast cases use a naive same-hour-last-week forecast; there is no better
  forecasting model.
- Svenska kraftnät publishes two procurement rounds (D-2 and D-1) and no "Total" series.
  The model uses their volume-weighted mean ([DATA.md](DATA.md)).
- Each UTC day is planned on its own and starts and ends at 50 % of the usable energy.
  FCR activation energy, its settlement and the imbalance it causes are not part of the
  plan.
- The reference case is hourly: the 15-minute day-ahead prices from 2025-10-01 are
  averaged, and only the 15-minute case uses them directly. In the forecast cases every
  offer is accepted at the clearing price (bids at 0 EUR/MW/h).
- Intraday and mFRR markets are not modelled.
- Before February 2024 Svenska kraftnät published average rather than marginal FCR
  prices, so the price history for 2021-2023 is only indicative.

## Battery and controller

- Constant charge and discharge efficiency (0.9487 each, 90 % round trip), no auxiliary
  load and no capacity fade. Degradation is a linear cost of 10 EUR per MWh discharged.
- The converter is a first-order lag with a 0.2 s time constant, and the frequency
  measurement is ideal.
- The Table 11 thresholds are used as printed. The TSOs allow moving the disable
  thresholds for reservoirs larger than the minimum, which would let NEM bring the state
  of charge back to 50 %.
- When several products are sold, the FCR-D energy reserves sit at the edges of the
  usable range and the FCR-N thresholds move inwards. This is my reading of section 3.5.
- Only one week of measured frequency (March 2025) is simulated.

## Prequalification tests

- These are simulations, not field tests: there is no measurement noise and no dependence
  on temperature or load. The test signal goes straight into the controller, so the
  transfer function of the frequency measurement equipment (section 4.4) is left out.
- The steady-state power of a hold is the mean of its last 60 s. The requirements accept
  "small damped oscillations" after 7.5 s, which I implement as a 1 % tolerance.
- Not evaluated: Requirement 1b (FCR-N and FCR-D combined), 5-7 and 11 (static FCR-D)
  and 13 (mode shifting, which a battery does not use).
- Requirement 8 uses G0 = F·G as in eq. 10, while the requirement box prints -F·G.
  [FCR_SPEC_NOTES.md](FCR_SPEC_NOTES.md) explains why.
