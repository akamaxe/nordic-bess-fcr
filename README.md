# nordic-bess-fcr

**A battery in SE3, from market decision to real-time control, checked against the Nordic
FCR prequalification requirements (v1.1).**

> Work in progress. See [docs/PLAN.md](docs/PLAN.md) for the roadmap.

<!-- Key result figure goes here (produced by scripts/run_backtest.py) -->

## The problem
A battery owner in the Nordic market has to decide every day how to split capacity between
frequency containment reserves (FCR-N, FCR-D up, FCR-D down) and day-ahead arbitrage, and
then deliver that promise second by second without running out of energy. The rules for
doing so are set by the Nordic TSOs' FCR technical requirements.

## Architecture
<!-- Mermaid diagram: market layer -> asset layer -> validation layer -->

## Results
<!-- Revenue per strategy (EUR/MW-year) -->
<!-- Compliance table: requirement / measured / threshold / pass -->

## Reproduce in 5 commands
<!-- uv sync ... run_compliance.py -->

## Assumptions and limitations
<!-- price taker, perfect foresight, hourly resolution, ... -->

## Roadmap
See [docs/PLAN.md](docs/PLAN.md).

## References
- ENTSO-E et al., *Technical Requirements for Frequency Containment Reserve Provision in the
  Nordic Synchronous Area*, v1.1, 28 March 2025.
- Data: ENTSO-E Transparency Platform; Svenska kraftnat data portal (CC BY 4.0);
  Fingrid open data.

## Licence
MIT
