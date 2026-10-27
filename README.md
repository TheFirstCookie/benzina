# ANRE fuel prices

Fetches ANRE Moldova's petrol and diesel price history, generates a chart, and sends it to Telegram. Scheduled runs wait until 12:15 Europe/Chisinau; later runs send immediately. A daily cache marker skips subsequent successful scheduled deliveries. Manual runs send immediately and bypass that marker.

If either history page is unreachable, the bot uses the [official e-carburanți API](https://api.ecarburanti.anre.md/public/plafon/) to send both fuel price caps currently in force. This report is explicitly titled **Preturi in vigoare**, shows the API's date and a two-bar chart, and omits daily/weekly changes. These current caps can differ from the latest prices announced for tomorrow in the history pages. The bot resumes the history report automatically when both pages are reachable. No third-party relay or cached price snapshot is used.

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
- `current-prices-response.json`: the last official API response when history retrieval fails. The summary identifies this source and that its prices are currently in force.

`ConnectTimeout` means the runner could not establish the connection; `ReadTimeout` means the server did not return data in time; DNS errors indicate hostname resolution failure. HTTP 403/429 suggests access denial/rate limiting; 5xx suggests a server issue. Missing valid price rows points to page content; inspect the saved HTML. Telegram errors show its HTTP status and API description. Telegram tokens and chat IDs are redacted from application logs and summaries; Telegram responses are not stored as artifacts.

Requests use verified HTTPS, a 10-second connection timeout and a 30-second read timeout. Two history attempts alternate `anre.md` and `www.anre.md`, with 5 seconds between attempts, before switching to the official API. The API gets up to three attempts with the same delay. Both prices must be finite positive numbers below 1000 lei, and the API date must be neither future nor older than seven days (allowing weekends/holidays). Invalid responses or failure of both official services fail the run without claiming delivery. Failed sends do not create the scheduled delivery marker. Telegram sends are not retried automatically because an ambiguous timeout could otherwise cause duplicate messages.

Every workflow run that has not already delivered the daily message runs the unit tests before starting the bot. Tests cover history parsing, retry recovery, fallback after either fuel's history fails, API validation, chart/caption generation, and Telegram failure handling.

## October 27, 2026 investigation

The [failed scheduled run](https://github.com/TheFirstCookie/benzina/actions/runs/40505115451) confirms connection timeouts to both ANRE history hostnames, which resolve to the same IP (`185.108.181.122`). The independent curl checks also timed out while Telegram was reachable. Both history pages returned valid tables from the local computer. This establishes a runner-to-ANRE connectivity issue; it does not identify which network or firewall drops the connection.

A [comparison across Ubuntu, Ubuntu ARM, macOS and Windows runners](https://github.com/TheFirstCookie/benzina/actions/runs/40507684915) reproduced the timeout on all four, so changing operating systems was insufficient. A [subsequent probe](https://github.com/TheFirstCookie/benzina/actions/runs/40510676172) confirmed HTTP 200 from ANRE's separate official e-carburanți API (`185.108.182.178`) on GitHub. The bot therefore keeps Ubuntu and falls back to this reachable official source.

## October 26, 2026 investigation

Both the [manual run](https://github.com/TheFirstCookie/benzina/actions/runs/40315015554) and [scheduled run](https://github.com/TheFirstCookie/benzina/actions/runs/40330883638) completed setup and dependency installation, then failed in `Rulare bot` after about 560 seconds. That closely matches eight 30-second request timeouts plus seven 45-second retry delays (555 seconds). Repeated ANRE request timeouts are therefore the leading explanation, rather than a setup failure. The exact original exception is unconfirmed: GitHub's log-download endpoint required authenticated repository access. Both official ANRE hostnames returned valid price tables during the local investigation. The added diagnostics are intended to distinguish a transient outage, runner-specific connectivity, TLS issues, HTTP errors and changed HTML on the next run.
