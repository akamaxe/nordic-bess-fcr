# Executive summary

How should a 10 MW / 20 MWh battery in the Swedish SE3 zone split its capacity between
frequency containment reserves and day-ahead trading, and can its controller meet the
Nordic TSOs' FCR rules? This summary uses 2025 market data and the FCR technical
requirements v1.1. The numbers come from `results/*.csv`.

## Revenue in 2025

| Strategy | kEUR per MW-year |
| --- | ---: |
| Day-ahead arbitrage only | 44 |
| FCR-D up and down only | 84 |
| FCR-N only | 173 |
| Everything co-optimised, perfect foresight (upper bound) | 193 |
| Co-optimised, bids on last week's prices | 163 |
| Co-optimised, bids on four past weeks as scenarios | 169 |

For planning, 160-170 kEUR per MW-year is a realistic figure. For this battery that is
1.6-1.7 MEUR a year before fees, grid tariffs, imbalance costs and taxes.

## Where the revenue comes from

FCR-N paid 26 EUR/MW/h on average in 2025, more than four times as much as FCR-D, and
it makes up over three quarters of the co-optimised revenue.

The FCR rules limit how much can be sold. For every MW of FCR-N, the battery has to keep
1.34 MW of power and one hour of energy in reserve in each direction. A 10 MW battery can
therefore sell at most 7.5 MW of FCR-N, and that power limit is binding in 94 % of the
hours.

Once the capacity is sold, day-ahead trading adds only about 10 % of the revenue. The
move to 15-minute day-ahead prices in October 2025 made almost no difference to this
strategy.

## Risks

1. Falling FCR prices (high). FCR prices in SE3 have dropped sharply as batteries
   entered a small market. FCR-N went from 89 EUR/MW/h in 2022 to 26 in 2025, and FCR-D
   up from 86 to 6. Prices before 2024 are averages rather than marginal prices, so they
   are only indicative. The 2025 revenue already reflects most of the fall, but if FCR-N
   prices halved again the battery would lose up to about 75 kEUR per MW-year, half of
   its FCR-N revenue before re-optimising.
2. Rule changes (medium). The TSOs will review the energy reservation, and FCR-N may
   need 1.5 h of energy per direction instead of 1 h. That would cut revenue by
   24 kEUR per MW-year (13 %). More energy capacity per MW of power is a hedge.
3. Forecasting (medium). FCR capacity is sold before prices are known. Bidding on last
   week's prices loses 29 kEUR per MW-year compared with perfect foresight, and a simple
   scenario-based optimiser wins back 5 of them.
4. Operations (manageable). In a simulated week on measured grid frequency the battery
   was available for FCR the whole time, but its state of charge drifted away from the
   plan and 4.6 MWh of day-ahead energy could not be delivered. The scheduler needs to
   re-plan from the measured state of charge.
5. Prequalification (low). In simulation the controller passes all 24 prequalification
   checks evaluated, including the energy-management tests for batteries, and a Simulink
   model of the same controller gives the same results. Field tests are still required.

## Recommendation

- Base the business case on FCR-N with FCR-D where it pays, valued at 2025 price levels,
  with a downside case at half the FCR-N price.
- Size the energy capacity for a possible 1.5 h FCR-N rule and keep the 50 % state of
  charge target.
- Put effort into price forecasting and re-planning from the measured state of charge
  before adding more trading strategies.

*Method and limitations are in the [README](../README.md). FCR prices: Svenska kraftnät
(CC BY 4.0). Day-ahead prices: ENTSO-E. Frequency: Fingrid (CC BY 4.0).*
