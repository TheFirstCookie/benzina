# Refactoring verification

Each numbered step is verified before its commit is pushed. Dry runs never post to Telegram.

1. **Configuration:** central `Settings`, validated `HH:MM`, credentials excluded from repr; configuration tests and existing regression suite.

2. **Sources:** ANRE HTTP access, hostname retries, response artifacts and mirror retries live in `fuelbot/sources.py`; parser/retry/fallback regression tests pass.

3. **Data model:** immutable `PricePoint`, `FuelHistory` and `Report` records replace HTML rows outside fetching; both sources and the relay round-trip through the same price/date data. Original caption and PNG regression tests pass.
