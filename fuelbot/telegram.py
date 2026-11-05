"""Telegram delivery with explicit rejection versus uncertain delivery."""
import io
import logging

import requests

from .config import CONNECT_TIMEOUT, REQUEST_TIMEOUT


class TelegramRejected(RuntimeError):
    """Telegram explicitly rejected the message; a later attempt is safe."""


class TelegramUncertain(RuntimeError):
    """Delivery might have occurred; do not automatically resend."""


def send_photo(settings, image, caption):
    settings.require_telegram()
    if not image or len(caption) > 1024:
        raise ValueError("Telegram requires an image and a caption of at most 1024 characters")
    logging.info("Sending Telegram photo: bytes=%d caption_characters=%d", len(image), len(caption))
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{settings.bot_token}/sendPhoto",
            data={"chat_id": settings.chat_id, "caption": caption, "parse_mode": "Markdown"},
            files={"photo": ("chart.png", io.BytesIO(image), "image/png")},
            timeout=(CONNECT_TIMEOUT, REQUEST_TIMEOUT))
    except requests.RequestException as error:
        raise TelegramUncertain(f"Telegram delivery could not be confirmed ({type(error).__name__})") from error
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if (isinstance(payload, dict) and payload.get("ok") is False
            and response.status_code < 500):
        raise TelegramRejected(f"Telegram sendPhoto failed ({response.status_code}): "
                               f"{payload.get('description', 'request rejected')}")
    message = payload.get("result") if isinstance(payload, dict) else None
    message_id = message.get("message_id") if isinstance(message, dict) else None
    if (not response.ok or not isinstance(payload, dict) or payload.get("ok") is not True
            or isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0):
        raise TelegramUncertain(f"Telegram returned no verifiable message ID (HTTP {response.status_code})")
    logging.info("Telegram delivery confirmed: message_id=%s", message_id)
    return message_id
