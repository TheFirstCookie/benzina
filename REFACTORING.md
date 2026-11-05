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

9. **Diagnostics:** UTC logs, stage history and redacted text/JSON summaries distinguish invalid data, source/network errors, Telegram rejection/uncertainty and delivery-storage failures. Token/chat/GitHub credential redaction tests and failure-category tests pass.

10. **Tests and final integration:** the suite now has 56 tests organized by module under `tests/`, including the original Friday caption fixture. Temporary monolith compatibility wrappers and import-time settings/stage globals have been removed. Tests cover application orchestration, midnight rollover, source normalization, shared validation, durable storage/restart/concurrency/owner checks, corrupt records, Telegram uncertainty, secret redaction and isolated dry runs. A separate CI workflow checks Ubuntu Python 3.12/3.14 and Windows Python 3.12. Local checks passed with `GITHUB_ACTIONS=true`, both workflows passed actionlint, and compilation and background `pythonw.exe` relay validation succeeded. The installed Windows task remains ready for 12:43 Chisinau time on the next weekday.

## Verified checkpoints

| Step | Local suite | Additional check |
| --- | --- | --- |
| 1 | 27 tests | Invalid send times and settings redaction |
| 2 | 27 tests | Parser, alternate hostname, retry and mirror regressions |
| 3 | 27 tests | Live official history and relay serialization |
| 4 | 31 tests | Common invalid-price/date and round-trip checks |
| 5 | 31 tests | Live original chart and caption generation |
| 6 | 34 tests | Confirmed ID, rejection and uncertain response checks |
| 7 | 34 tests | Scheduler ordering, DST and CLI startup |
| 8 | 43 tests | Live GitHub ledger write/read and duplicate suppression |
| 9 | 45 tests | Live JSON diagnostics and secret-redaction checks |
| 10 | 56 tests | Actions environment, workflow syntax, compilation and Windows background relay |

Each checkpoint was committed with the repository's configured author (Daniel) and pushed to `main` after its checks passed. No test posted a Telegram message. Historical investigations are retained in `docs/INCIDENTS.md`.
