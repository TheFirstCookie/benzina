# ANRE fuel prices

Fetches ANRE Moldova's petrol and diesel price history, generates the original blue/green line chart, and sends it to Telegram with daily price comparisons and Friday's weekly summary. Scheduled weekday runs prepare the report from 12:45 and send at **12:50 PM Europe/Chisinau**, automatically following winter/summer time; later runs send immediately. GitHub cron can be delayed by hours, so multiple early starts and retries are retained. Runs arriving before 07:15 local exit, keeping the wait within the runner's job limit. A daily cache marker skips subsequent automated deliveries. Manual runs bypass that check but now also record successful delivery. All real sends share one concurrency group so manual and automated runs cannot race each other.

The bot tries both official history hostnames over HTTPS. If either fuel is unavailable, it fetches both publication histories from the [Logos Press ANRE history feed](https://logos-pres.md/wp-json/logos/v1/fuel-prices?days=30&lang=ro). This preserves the original line chart, publication dates, daily comparisons and Friday summary. Fallback reports retain the original ANRE source links and add `Date ANRE preluate prin logos-pres.md` to identify the intermediary. The feed's latest ten publications were compared with both official tables on October 27. No current-cap bar chart or cached price snapshot is used.

## Run and test

Install Python 3.12+ and `python -m pip install -r requirements.txt`.

```sh
python -m unittest -v
python bot.py --dry-run --debug
```

Dry runs need no Telegram secrets, do not wait for the send time, and save the chart and caption in `diagnostics/`. Real delivery requires `BOT_TOKEN` and `CHAT_ID` environment variables (GitHub Actions repository secrets). Optional variables: `TIMEZONE`, `SEND_AT` (`HH:MM`), and `DIAGNOSTICS_DIR`.

In GitHub: **Actions > Pret Carburanti ANRE > Run workflow**. Check **dry_run** to test without posting; check **debug** for application debug logging. Leave dry_run unchecked for a real message.

## Investigating failures

Open the run's **Summary** for the failed stage and error. Download its `diagnostics-<run id>-<attempt>` artifact (retained for 14 days):

- `bot.log`: timestamped stages, request attempt, hostname, response status, timing, row count, latest date/price, and exception traceback.
- `*.html` / `*.json`: last received ANRE page and selected response metadata per hostname and fuel. These distinguish a changed table, maintenance page, access denial, or HTTP error. Connection failures produce no response files.
- `runtime.txt`: Python and dependency versions, runner and run identifiers.
- `network.txt`: after a failure, DNS and unauthenticated HTTPS checks for both ANRE hostnames and Telegram. A successful check later does not prove the earlier request worked.
- `chart.png`, `caption.txt`, `summary.txt`: generated output and result, when reached.
- `mirrored-history.json`: the ANRE publication-history response from Logos Press when direct ANRE access fails.

`ConnectTimeout` means the runner could not establish the connection; `ReadTimeout` means the server did not return data in time; DNS errors indicate hostname resolution failure. HTTP 403/429 suggests access denial/rate limiting; 5xx suggests a server issue. Missing valid price rows points to page content; inspect the saved HTML. Telegram errors show its HTTP status and API description. Telegram tokens and chat IDs are redacted from application logs and summaries; Telegram responses are not stored as artifacts.

Requests use verified HTTPS, a 10-second connection timeout and a 30-second read timeout. Two direct history attempts alternate `anre.md` and `www.anre.md`, with 5 seconds between attempts. The mirror gets up to three attempts. All histories must have today's publication date (Friday on weekends) and matching petrol/diesel dates. Mirrored and supplied data must also identify ANRE as the source, contain at least six valid prices per fuel, and agree with the advertised latest prices and daily changes. Stale data, including a holiday without a new publication, fails explicitly instead of being posted as a new daily update. A failure of both direct history and the mirror fails the run without claiming delivery. Failed sends and dry runs do not create the daily marker. Telegram sends are not retried automatically because an ambiguous timeout could otherwise cause duplicate messages.

Every workflow run that has not already delivered the daily message runs the unit tests before starting the bot. Tests cover history parsing, mirror recovery and validation, the exact original Friday caption, failure without partial reports, 12:50 local scheduling in winter/summer, chart generation, and Telegram failure handling.

## Optional Windows scheduler

On a Windows computer that can reach ANRE, `dispatch_prices.py` fetches both official histories and passes validated price/date JSON to a manual GitHub Actions dispatch. This avoids both the delayed GitHub cron event and the runner-to-ANRE network failure. The Telegram token stays in repository secrets. The relay uses the existing Git credential manager login, without saving a second GitHub token. Its history is revalidated on the runner before rendering the original report.

```powershell
.venv\Scripts\python.exe dispatch_prices.py --prepare-only
.venv\Scripts\python.exe dispatch_prices.py --dry-run
powershell -NoProfile -ExecutionPolicy Bypass -File install_schedule.ps1
```

The first command only validates locally. The second dispatches a GitHub dry run without Telegram delivery. The last installs the task for the current user at 12:43, 12:53 and 13:03 on weekdays. Windows must use the Chisinau time zone, and the user must be signed in with internet access; the task requests wake from sleep, but cannot start a powered-off computer. The extra triggers retry failures; daily marker checks suppress successful duplicates. Logs and fetched history are in `diagnostics/relay/`. GitHub cron remains a backup. Runner availability can still delay dispatch, so this improves punctuality without guaranteeing delivery to the second.

Remove the task with `Unregister-ScheduledTask -TaskName 'ANRE fuel prices - GitHub dispatch' -Confirm:$false`. Running the installer again updates the same task.

## November 5, 2026 investigation

The [November 5 scheduled run](https://github.com/TheFirstCookie/benzina/actions/runs/42049597119) was only created at 14:54 UTC (16:54 Chisinau), after the earliest configured 06:37 UTC opportunity. Its bot log confirms both official hostnames timed out, the Logos feed returned November 3 publications, and Telegram accepted message 332 at 14:55:26 UTC. The [November 4 first run](https://github.com/TheFirstCookie/benzina/actions/runs/41851407142) also delivered the November 3 publication. These runs demonstrate late delivery and stale fallback data; they do not demonstrate that Telegram rejected the messages.

On November 5 the local official tables contained the November 5 publication: petrol 30.80 and diesel 35.94 lei/litre. The old seven-day freshness rule allowed the frozen mirror to be marked as a successful daily delivery, suppressing later attempts. Freshness validation, earlier cron opportunities, shared send concurrency, and the optional local relay address these separate problems. The relay is only active after installing its Windows task.

## October 27, 2026 investigation

The earlier current-cap fallback described below changed the Telegram appearance and omitted comparisons. It has been removed. A [GitHub dry run](https://github.com/TheFirstCookie/benzina/actions/runs/40554263064) confirmed direct HTTP also times out, so the bot now uses the validated Logos Press publication-history feed when the official pages are unreachable.

The [failed scheduled run](https://github.com/TheFirstCookie/benzina/actions/runs/40505115451) confirms connection timeouts to both ANRE history hostnames, which resolve to the same IP (`185.108.181.122`). The independent curl checks also timed out while Telegram was reachable. Both history pages returned valid tables from the local computer. This establishes a runner-to-ANRE connectivity issue; it does not identify which network or firewall drops the connection.

A [comparison across Ubuntu, Ubuntu ARM, macOS and Windows runners](https://github.com/TheFirstCookie/benzina/actions/runs/40507684915) reproduced the timeout on all four, so changing operating systems was insufficient. A [subsequent probe](https://github.com/TheFirstCookie/benzina/actions/runs/40510676172) confirmed HTTP 200 from ANRE's separate official e-carburanți API (`185.108.182.178`) on GitHub. The bot therefore keeps Ubuntu and falls back to this reachable official source.

The [verified dry run](https://github.com/TheFirstCookie/benzina/actions/runs/40511397799) passed all 14 tests, reproduced both history connection timeouts, then fetched current caps from the official API and generated the chart and caption successfully. It did not send a Telegram message.

## October 26, 2026 investigation

Both the [manual run](https://github.com/TheFirstCookie/benzina/actions/runs/40315015554) and [scheduled run](https://github.com/TheFirstCookie/benzina/actions/runs/40330883638) completed setup and dependency installation, then failed in `Rulare bot` after about 560 seconds. That closely matches eight 30-second request timeouts plus seven 45-second retry delays (555 seconds). Repeated ANRE request timeouts are therefore the leading explanation, rather than a setup failure. The exact original exception is unconfirmed: GitHub's log-download endpoint required authenticated repository access. Both official ANRE hostnames returned valid price tables during the local investigation. The added diagnostics are intended to distinguish a transient outage, runner-specific connectivity, TLS issues, HTTP errors and changed HTML on the next run.
