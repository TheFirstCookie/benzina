# Refactoring verification

Each numbered step is verified before its commit is pushed. Dry runs never post to Telegram.

1. **Configuration:** central `Settings`, validated `HH:MM`, credentials excluded from repr; configuration tests and existing regression suite.

2. **Sources:** ANRE HTTP access, hostname retries, response artifacts and mirror retries live in `fuelbot/sources.py`; parser/retry/fallback regression tests pass.

3. **Data model:** immutable `PricePoint`, `FuelHistory` and `Report` records replace HTML rows outside fetching; both sources and the relay round-trip through the same price/date data. Original caption and PNG regression tests pass.

4. **Validation:** a single module rejects stale/future dates, duplicates, mismatched products, malformed feeds and invalid/nonfinite/boolean prices for every source; round-trip and negative tests pass.

5. **Reports:** chart/caption creation is isolated from HTTP and sending in `fuelbot/reports.py`; exact Friday caption regression and real PNG generation pass.

6. **Telegram:** isolated client returns confirmed message IDs and distinguishes explicit rejection from ambiguous delivery, with no automatic resend after a timeout; response/timeout tests pass.

7. **Scheduling:** `fuelbot/scheduler.py` owns preparation/send waits; reporting workers execute immediately and `bot.py` is a CLI entry point. Scheduled ordering, late starts, winter/summer and dry-run no-wait tests pass.

8. **Delivery tracking:** SQLite persists local state and the `bot-deliveries` Git branch persists Actions state. Atomic reservations, confirmed message IDs, explicit rejection retries, ambiguous timeout blocking, process restart, concurrent reservation and storage failure tests pass (43 tests total). Live GitHub read/write verified by importing the already-confirmed November 5 message 332, then verifying a second reservation is blocked; no Telegram message was sent.
