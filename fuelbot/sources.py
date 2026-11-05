"""HTTP access to ANRE and the independent publication-history mirror."""
import json
import logging
import socket
import time
from urllib.parse import urlsplit, urlunsplit
import requests
from bs4 import BeautifulSoup
from .config import (CONNECT_TIMEOUT, REQUEST_TIMEOUT, FETCH_ATTEMPTS,
                     FETCH_RETRY_DELAY, HISTORY_MIRROR_URL, MIRROR_ATTEMPTS)
from .parsing import parse_date, parse_price
from .models import PricePoint
from .validation import decode_history

class SourceUnavailable(RuntimeError):
    """A source could not return usable publication history."""


def log_dns(url):
    host = urlsplit(url).hostname
    try:
        addresses = sorted({entry[4][0] for entry in socket.getaddrinfo(
            host, 443, type=socket.SOCK_STREAM)})
        logging.info("DNS %s: %s", host, addresses)
    except OSError as error:
        logging.error("DNS %s failed: %s", host, error)


def fetch_anre_page(url, diagnostics_dir):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ANREPriceBot/1.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ro,en;q=0.8",
    }

    started = time.monotonic()
    r = requests.get(
        url,
        headers=headers,
        timeout=(CONNECT_TIMEOUT, REQUEST_TIMEOUT)
    )
    logging.info("ANRE response: status=%s url=%s elapsed=%.2fs bytes=%d type=%s",
                 r.status_code, r.url, time.monotonic() - started,
                 len(r.content), r.headers.get("Content-Type", "unknown"))
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{urlsplit(url).netloc}-{urlsplit(url).path.strip('/')}"
    (diagnostics_dir / f"{filename}.html").write_text(r.text, encoding="utf-8")
    (diagnostics_dir / f"{filename}.json").write_text(json.dumps({
        "url": r.url, "status": r.status_code,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "bytes": len(r.content), "content_type": r.headers.get("Content-Type"),
        "server": r.headers.get("Server"),
        "retry_after": r.headers.get("Retry-After"),
    }, indent=2), encoding="utf-8")
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    logging.debug("ANRE page title=%r table_count=%d",
                  soup.title.get_text(strip=True) if soup.title else None,
                  len(soup.find_all("table")))
    # Ignore layout tables and header rows that use td instead of th.
    for table in soup.find_all("table"):
        rows = []
        for row in table.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) < 2 or parse_date(cols[0].get_text(" ", strip=True)) is None:
                continue
            try:
                price = parse_price(cols[-1].get_text(strip=True))
                if not 0 < price < 1000:
                    continue
            except ValueError:
                logging.debug("Skipping invalid ANRE price on date %r",
                              cols[0].get_text(strip=True))
                continue
            rows.append(PricePoint(parse_date(cols[0].get_text(" ", strip=True)), price))
        if len(rows) >= 2:
            rows.sort(key=lambda point: point.date,
                      reverse=True)
            logging.info("ANRE parsed %d prices; latest date=%s price=%s", len(rows),
                         rows[0].date.date(), rows[0].price)
            return rows
    title = soup.title.get_text(strip=True) if soup.title else "(no title)"
    raise SourceUnavailable(f"ANRE page has fewer than two valid price rows: {url}; "
                       f"title={title!r}; tables={len(soup.find_all('table'))}; "
                       "see diagnostics HTML")


def fetch_anre(url, diagnostics_dir, fetch=None):
    fetch = fetch or (lambda candidate: fetch_anre_page(candidate, diagnostics_dir))
    # anre.md uneori raspunde cu o pagina fara tabel sau nu raspunde deloc
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        parts = urlsplit(url)
        host = "www.anre.md" if attempt % 2 == 0 else parts.netloc
        candidate = urlunsplit(parts._replace(netloc=host))
        started = time.monotonic()
        logging.info("ANRE attempt %d/%d: %s", attempt, FETCH_ATTEMPTS, candidate)
        try:
            return fetch(candidate)
        except (requests.RequestException, RuntimeError) as e:
            logging.warning("ANRE %s after %.1fs: %s", type(e).__name__,
                            time.monotonic() - started, e)
            if attempt == FETCH_ATTEMPTS:
                log_dns(url)
                log_dns(candidate)
                raise SourceUnavailable(
                    f"ANRE fetch failed after {FETCH_ATTEMPTS} attempts: "
                    f"{type(e).__name__}: {e}"
                ) from e
            logging.warning(
                "Incercarea %d/%d a esuat pentru %s: %s",
                attempt, FETCH_ATTEMPTS, candidate, e
            )
            time.sleep(FETCH_RETRY_DELAY)


def fetch_mirror(now, diagnostics_dir):
    for attempt in range(1, MIRROR_ATTEMPTS + 1):
        logging.info("ANRE history mirror attempt %d/%d: %s", attempt,
                     MIRROR_ATTEMPTS, HISTORY_MIRROR_URL)
        try:
            response = requests.get(HISTORY_MIRROR_URL,
                                    timeout=(CONNECT_TIMEOUT, REQUEST_TIMEOUT))
            response.raise_for_status()
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            (diagnostics_dir / "mirrored-history.json").write_text(response.text, encoding="utf-8")
            histories = decode_history(response.json(), now, source=HISTORY_MIRROR_URL)
            logging.info("Validated mirrored ANRE history: %s", response.json()["source"]["published_date"])
            return histories
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            logging.warning("ANRE history mirror failed: %s", error)
            if attempt == MIRROR_ATTEMPTS:
                raise SourceUnavailable(f"ANRE history mirror failed after {attempt} attempts: {error}") from error
            time.sleep(FETCH_RETRY_DELAY)

