"""Reserve before sending and persist the confirmed Telegram message ID."""
import logging

from .telegram import TelegramRejected


def deliver_once(ledger, key, send, force=False):
    reservation = ledger.reserve(key, force=force)
    if reservation is None:
        logging.info("Delivery %s already sent, reserved or uncertain; skipping", key)
        return None
    try:
        message_id = send()
    except Exception as error:
        status = "failed" if isinstance(error, TelegramRejected) else "uncertain"
        try:
            ledger.finish(reservation, status)
        except Exception:
            logging.exception("Could not update delivery status; existing reservation prevents automatic resend")
        raise
    try:
        ledger.finish(reservation, "sent", message_id)
    except Exception as error:
        raise RuntimeError(f"Telegram accepted message {message_id}, but its delivery record could not be confirmed; "
                           "the reservation blocks automatic resending") from error
    return message_id
