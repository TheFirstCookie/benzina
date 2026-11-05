# Historical investigations

These sections describe earlier behavior. See the main README for current operation.

## November 5, 2026 investigation

The [November 5 scheduled run](https://github.com/TheFirstCookie/benzina/actions/runs/42049597119) was only created at 14:54 UTC (16:54 Chisinau), after the earliest configured 06:37 UTC opportunity. Its bot log confirms both official hostnames timed out, the Logos feed returned November 3 publications, and Telegram accepted message 332 at 14:55:26 UTC. The [November 4 first run](https://github.com/TheFirstCookie/benzina/actions/runs/41851407142) also delivered the November 3 publication. These runs demonstrate late delivery and stale fallback data; they do not demonstrate that Telegram rejected the messages.

On November 5 the local official tables contained the November 5 publication: petrol 30.80 and diesel 35.94 lei/litre. The old seven-day freshness rule allowed the frozen mirror to be marked as a successful daily delivery, suppressing later attempts. Freshness validation, earlier cron opportunities, shared send concurrency, and the optional local relay address these separate problems. The relay is only active after installing its Windows task.

The [verified relay dry run](https://github.com/TheFirstCookie/benzina/actions/runs/42062171434) passed all 24 tests on GitHub, used the supplied November 5 official publication, and generated the original chart/caption with 30.80 and 35.94 lei/litre. It skipped Telegram sending and both delivery-marker steps. Local background execution with `pythonw.exe` also validated the official histories successfully. Windows task triggers use local wall-clock boundaries so they follow Chisinau's daylight-saving changes.

## October 27, 2026 investigation

The earlier current-cap fallback described below changed the Telegram appearance and omitted comparisons. It has been removed. A [GitHub dry run](https://github.com/TheFirstCookie/benzina/actions/runs/40554263064) confirmed direct HTTP also times out, so the bot now uses the validated Logos Press publication-history feed when the official pages are unreachable.

The [failed scheduled run](https://github.com/TheFirstCookie/benzina/actions/runs/40505115451) confirms connection timeouts to both ANRE history hostnames, which resolve to the same IP (`185.108.181.122`). The independent curl checks also timed out while Telegram was reachable. Both history pages returned valid tables from the local computer. This establishes a runner-to-ANRE connectivity issue; it does not identify which network or firewall drops the connection.

A [comparison across Ubuntu, Ubuntu ARM, macOS and Windows runners](https://github.com/TheFirstCookie/benzina/actions/runs/40507684915) reproduced the timeout on all four, so changing operating systems was insufficient. A [subsequent probe](https://github.com/TheFirstCookie/benzina/actions/runs/40510676172) confirmed HTTP 200 from ANRE's separate official e-carburanți API (`185.108.182.178`) on GitHub. The bot therefore keeps Ubuntu and falls back to this reachable official source.

The [verified dry run](https://github.com/TheFirstCookie/benzina/actions/runs/40511397799) passed all 14 tests, reproduced both history connection timeouts, then fetched current caps from the official API and generated the chart and caption successfully. It did not send a Telegram message.

## October 26, 2026 investigation

Both the [manual run](https://github.com/TheFirstCookie/benzina/actions/runs/40315015554) and [scheduled run](https://github.com/TheFirstCookie/benzina/actions/runs/40330883638) completed setup and dependency installation, then failed in `Rulare bot` after about 560 seconds. That closely matches eight 30-second request timeouts plus seven 45-second retry delays (555 seconds). Repeated ANRE request timeouts are therefore the leading explanation, rather than a setup failure. The exact original exception is unconfirmed: GitHub's log-download endpoint required authenticated repository access. Both official ANRE hostnames returned valid price tables during the local investigation. The added diagnostics are intended to distinguish a transient outage, runner-specific connectivity, TLS issues, HTTP errors and changed HTML on the next run.
