"""Data loaders: ENTSO-E day-ahead prices, Svk FCR capacity prices, Fingrid frequency.

Loaders convert every timestamp to tz-aware UTC at the boundary and validate the
index (monotonic, unique, expected resolution, gap report) before returning data.
"""
