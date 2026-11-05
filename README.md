# ANRE fuel prices

Fetches ANRE Moldova publication history for petrol 95 and diesel, preserving the original blue/green chart, Romanian caption, daily comparisons and Friday summary.

Automated delivery targets **12:50 PM Europe/Chisinau** on weekdays. The Windows relay starts at 12:43 with 12:53/13:03 retries and requires this computer signed in and online. GitHub cron provides backup opportunities; scheduled events and runner starts can still be delayed. No new always-on hosting service has been configured.

## Architecture

| Module | Responsibility |
| --- | --- |
| `fuelbot/config.py` | Validated environment settings; secrets excluded from repr |
| `fuelbot/sources.py`, `parsing.py` | ANRE/mirror requests, retries, HTML/date/price parsing |
| `fuelbot/models.py` | Immutable price, history and report records |
| `fuelbot/validation.py` | Shared freshness, matching dates, ordering, duplicates and valid prices |
| `fuelbot/reports.py` | Chart and caption generation without network calls |
| `fuelbot/telegram.py` | Telegram transport and confirmed message IDs |
| `fuelbot/scheduler.py` | Preparation/send waits, outside the reporting worker |
| `fuelbot/storage.py`, `delivery.py` | Durable reservations and delivery outcomes |
| `fuelbot/diagnostics.py` | UTC logs, credential redaction, stage history and JSON/text summaries |
| `fuelbot/app.py`, `relay.py` | Service orchestration with explicit settings and dependencies |
| `bot.py`, `dispatch_prices.py` | Stable CLI entry points |

HTML stops at the source boundary. Every source produces the same price/date records. If either official fuel is unavailable or invalid, both histories come from the [Logos Press ANRE feed](https://logos-pres.md/wp-json/logos/v1/fuel-prices?days=30&lang=ro), identified in the caption.

All histories must contain today's publication, or Friday's on weekends, with valid finite prices, unique descending dates and matching petrol/diesel dates. Mirrors and supplied histories must identify ANRE, contain at least six publications and agree with their advertised prices and changes. A holiday without a new publication fails explicitly instead of posting outdated prices.

## Run and test

Use Python 3.12 or later. Run installation and commands with your virtual environment's Python:

~~~sh
python -m pip install -r requirements.txt
python -m unittest -v
python bot.py --dry-run --debug
~~~

On this Windows checkout use `.venv\Scripts\python.exe`. Dry runs require no Telegram credentials, do not wait or contact Telegram, and never read or create delivery records. They save the chart, caption, logs and summaries in `diagnostics/`.

Tests preserve the exact original Friday caption and chart dimensions, and cover malformed/stale feeds, complete fallback reports, winter/summer scheduling, dry-run isolation, delivery orchestration, concurrent reservations, process restarts, uncertain sends, storage failures and credential redaction. The **Bot tests** workflow checks Ubuntu Python 3.12/3.14 and Windows Python 3.12 for pushes and pull requests.

For a cloud dry run: **Actions > Pret Carburanti ANRE > Run workflow > dry_run**. Use the Windows relay dry run below to supply fresh official history when the runner cannot reach ANRE.

## Configuration

| Variable | Default / purpose |
| --- | --- |
| `BOT_TOKEN`, `CHAT_ID` | Required for real sending; repository secrets on GitHub |
| `TIMEZONE` | `Europe/Chisinau` |
| `SEND_AT` | Empty: immediate; `HH:MM`: CLI invokes the separate scheduler |
| `DIAGNOSTICS_DIR` | `diagnostics` |
| `STATE_PATH` | `state/deliveries.sqlite3` for standalone local delivery |
| `GITHUB_TOKEN` | Durable GitHub storage; Actions supplies its temporary built-in token |
| `GITHUB_REPOSITORY` | `TheFirstCookie/benzina` |
| `DELIVERY_BRANCH` | `bot-deliveries` |
| `ANRE_HISTORY_JSON` | Optional validated relay history |

Source URLs, retry counts and timeouts are centralized in `config.py`. Requests verify HTTPS certificates and use a 10-second connection timeout and 30-second read timeout. Direct requests make two attempts, alternating official hostnames; the mirror makes up to three, with five seconds between retries. Telegram sends are never automatically retried.

## Durable delivery tracking

GitHub uses the dedicated [bot-deliveries branch](https://github.com/TheFirstCookie/benzina/tree/bot-deliveries), with one JSON record per date: status, reservation owner, timestamps, run ID and confirmed Telegram message ID. Tokens and chat IDs are excluded. Git history preserves changes without cache eviction. The workflow needs `contents: write` to update these records.

Standalone local sending uses SQLite with an event history. Retain `state/` across restarts. Supply `GITHUB_TOKEN` if a standalone installation should share GitHub's records. The Windows relay only dispatches GitHub jobs and checks the shared GitHub records.

| Status | Meaning |
| --- | --- |
| `reserved` | Claimed before sending; an interrupted process might have sent. |
| `sent` | Telegram returned a positive message ID and its record was persisted. |
| `failed` | Telegram explicitly rejected the request; a later run may retry. |
| `uncertain` | Delivery could not be confirmed; automatic resend is blocked. |

A reservation is written before contacting Telegram. If recording an accepted message fails, the reservation still blocks automatic resend. This reduces duplicate risk but cannot guarantee exactly-once delivery across a remote API and storage failure. Review the chat before overriding a reserved/uncertain record.

~~~sh
python bot.py --delivery-status 2026-11-05
python bot.py --force
~~~

The status command never contacts Telegram. Manual runs respect durable records too; intentional resending requires `--force` or the workflow's `force` input. November 5's previously confirmed message 332 was migrated from its verified run log during the transition from cache markers.

## Windows relay

The relay fetches official history locally and passes validated JSON to GitHub, which revalidates it and generates the report. The Telegram token stays in repository secrets. The relay uses the existing Git credential manager login without storing another token.

~~~powershell
.venv\Scripts\python.exe dispatch_prices.py --prepare-only
.venv\Scripts\python.exe dispatch_prices.py --dry-run
powershell -NoProfile -ExecutionPolicy Bypass -File install_schedule.ps1
~~~

The first command only validates locally; the second dispatches a cloud dry run. The installer creates or updates **ANRE fuel prices - GitHub dispatch** at 12:43, 12:53 and 13:03 on weekdays. Windows must use Chisinau time, with the user signed in and internet available. The task requests wake from sleep but cannot start a powered-off computer. Local wall-clock boundaries follow daylight-saving changes.

Background execution uses `pythonw.exe`; diagnostics are in `diagnostics/relay/`. Retries check durable records before fetching. GitHub serializes reporting jobs and the ledger makes a second atomic reservation immediately before sending. Accepted workflow dispatch is distinguished from confirmed Telegram delivery.

Remove the task with `Unregister-ScheduledTask -TaskName 'ANRE fuel prices - GitHub dispatch' -Confirm:$false`.

## Diagnosing failures

Open the run's **Summary** and its `diagnostics-<run id>-<attempt>` artifact, retained for 14 days:

- `bot.log`: UTC timestamps, stages, request timing and exception traceback.
- `summary.txt`, `summary.json`: result, failed stage, failure category and stage history.
- `*.html`, `*.json`: received source pages, response metadata and mirrored history.
- `chart.png`, `caption.txt`: prepared output, when reached.
- `runtime.txt`, `network.txt`: GitHub dependencies and failure-time connectivity probes.

Categories distinguish invalid data, unavailable sources, network/configuration errors, Telegram rejection/uncertainty, storage failures and internal errors. Credentials are redacted from application logs and summaries. Connection failures have no response file.

See [REFACTORING.md](REFACTORING.md) for verification and [docs/INCIDENTS.md](docs/INCIDENTS.md) for earlier investigations and run evidence.
