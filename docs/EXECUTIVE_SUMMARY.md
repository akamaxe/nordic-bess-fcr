# Executive summary: a 10 MW / 20 MWh battery in SE3

**Question.** How should a 10 MW / 20 MWh battery in the Swedish SE3 zone split its
capacity between frequency containment reserves and day-ahead trading, and can its
controller meet the Nordic TSOs' FCR rules? The analysis uses real 2025 market data and
the FCR technical requirements v1.1. Numbers come from `results/*.csv`.

## What the battery would have earned in 2025

| Strategy | kEUR per MW-year |
|---|---:|
| Day-ahead arbitrage only | 44 |
| FCR-D up and down only | 84 |
| FCR-N only | 173 |
| Everything co-optimised, perfect foresight (upper bound) | 193 |
| Co-optimised, bids on last week's prices | 163 |
| Co-optimised, bids on four past weeks as scenarios | 169 |

A realistic planning figure is **160-170 kEUR per MW-year**, or 1.6-1.7 MEUR a year for
this battery, before fees, grid tariffs, imbalance costs and taxes.

## What drives it

- **FCR-N is the product.** It paid 26 EUR/MW/h on average in 2025, more than four times
  FCR-D, and accounts for over three quarters of the co-optimised revenue.
- **The FCR rules cap what can be sold.** A battery must hold back 1.34 MW of power and
  one hour of energy in each direction for every MW of FCR-N sold. A 10 MW battery can
  therefore sell at most 7.5 MW of FCR-N, and that power limit binds in 94 % of hours.
- **Trading adds little once capacity is sold.** Arbitrage contributes about 10 % of the
  co-optimised revenue. The move to 15-minute day-ahead prices in October 2025 added
  almost nothing for this strategy.

## Risks

1. **Price cannibalisation (high).** FCR prices in SE3 have collapsed as batteries enter
   small markets. FCR-N fell from 89 EUR/MW/h in 2022 to 26 in 2025, and FCR-D up from 86
   to 6. Figures before 2024 are averages, not marginal prices, so they are indicative
   only. The 2025 revenue already reflects much of this fall, but a further halving of
   FCR-N prices would remove up to about 75 kEUR per MW-year (half of the FCR-N revenue,
   before re-optimising). Earlier years are not a guide.
2. **Rule changes (medium).** The TSOs will re-evaluate the energy reservation; FCR-N
   may need 1.5 h instead of 1 h per direction. That would cut revenue by
   **24 kEUR per MW-year (-13 %)**. Larger energy capacity per MW is a hedge.
3. **Forecasting (medium).** FCR capacity is sold before prices are known. Bidding on
   last week's prices loses 29 kEUR per MW-year against perfect foresight. A simple
   scenario-based optimiser recovers 5 of them, and better forecasts are worth money.
4. **Operations (manageable).** In a simulated week on measured grid frequency, the
   battery stayed available for FCR 100 % of the time. However, its state of charge
   drifted away from the plan, which caused 4.6 MWh of undelivered day-ahead energy. The
   scheduler must re-plan from the measured state of charge.
5. **Prequalification (low).** The controller passes all 24 checks of the FCR
   prequalification tests in simulation, including the energy-management tests for
   batteries. A Simulink model reproduces the Python results to within 0.00002 % of
   capacity. Field tests are still required.

## Recommendation

- Build the business case on **FCR-N plus opportunistic FCR-D**, valued at 2025 price
  levels with a downside case at half the FCR-N price.
- Size energy for the likely **1.5 h FCR-N rule** and keep the 50 % state-of-charge
  target.
- Invest in **price forecasting and state-of-charge-aware re-planning** before adding
  trading complexity.

*Method and limitations: [README](../README.md). FCR prices: Svenska kraftnat (CC BY 4.0);
day-ahead prices: ENTSO-E; frequency: Fingrid (CC BY 4.0).*
