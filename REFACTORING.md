# Refactoring verification

Each numbered step is verified before its commit is pushed. Dry runs never post to Telegram.

1. **Configuration:** central `Settings`, validated `HH:MM`, credentials excluded from repr; configuration tests and existing regression suite.
