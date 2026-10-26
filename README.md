# ANRE fuel prices

Fetches ANRE Moldova's petrol and diesel price history, generates a chart, and sends it to Telegram. Scheduled runs wait until 12:15 Europe/Chisinau; later runs send immediately. A daily cache marker skips subsequent successful scheduled deliveries. Manual runs send immediately and bypass that marker.

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

`ConnectTimeout` means the runner could not establish the connection; `ReadTimeout` means the server did not return data in time; DNS errors indicate hostname resolution failure. HTTP 403/429 suggests access denial/rate limiting; 5xx suggests a server issue. Missing valid price rows points to page content; inspect the saved HTML. Telegram errors show its HTTP status and API description. Telegram tokens and chat IDs are redacted from application logs and summaries; Telegram responses are not stored as artifacts.

Requests use verified HTTPS, a 10-second connection timeout and a 30-second read timeout. Up to eight attempts alternate `anre.md` and `www.anre.md`, with 45 seconds between attempts. Both hosts belong to the same service, so this cannot overcome a complete ANRE outage or a block affecting both hosts. Failed sends do not create the scheduled delivery marker. Telegram sends are not retried automatically because an ambiguous timeout could otherwise cause duplicate messages.

## October 26, 2026 investigation

Both the [manual run](https://github.com/TheFirstCookie/benzina/actions/runs/40315015554) and [scheduled run](https://github.com/TheFirstCookie/benzina/actions/runs/40330883638) completed setup and dependency installation, then failed in `Rulare bot` after about 560 seconds. That closely matches eight 30-second request timeouts plus seven 45-second retry delays (555 seconds). Repeated ANRE request timeouts are therefore the leading explanation, rather than a setup failure. The exact original exception is unconfirmed: GitHub's log-download endpoint required authenticated repository access. Both official ANRE hostnames returned valid price tables during the local investigation. The added diagnostics are intended to distinguish a transient outage, runner-specific connectivity, TLS issues, HTTP errors and changed HTML on the next run.
