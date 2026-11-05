"""Configuration shared by the reporter, scheduler and Windows relay."""
from dataclasses import dataclass, field
from datetime import time
import os
from pathlib import Path
from zoneinfo import ZoneInfo


URLS = {
    "Benzina 95": "https://anre.md/benzina-95-3-2",
    "Motorina": "https://anre.md/motorina-3-3",
}
HISTORY_MIRROR_URL = "https://logos-pres.md/wp-json/logos/v1/fuel-prices?days=30&lang=ro"
REQUEST_TIMEOUT = 30
CONNECT_TIMEOUT = 10
FETCH_ATTEMPTS = 2
FETCH_RETRY_DELAY = 5
MIRROR_ATTEMPTS = 3


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(default="", repr=False)
    chat_id: str = field(default="", repr=False)
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("Europe/Chisinau"))
    send_at: str = ""
    diagnostics_dir: Path = Path("diagnostics")
    state_path: Path = Path("state/deliveries.sqlite3")
    github_repository: str = "TheFirstCookie/benzina"
    github_token: str = field(default="", repr=False)
    delivery_branch: str = "bot-deliveries"

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        send_at = env.get("SEND_AT", "").strip()
        if send_at:
            try:
                parsed = time.fromisoformat(send_at)
                if parsed.strftime("%H:%M") != send_at:
                    raise ValueError
            except ValueError:
                raise ValueError("SEND_AT must use HH:MM (00:00 through 23:59)") from None
        return cls(
            bot_token=env.get("BOT_TOKEN", "").strip(),
            chat_id=env.get("CHAT_ID", "").strip(),
            timezone=ZoneInfo(env.get("TIMEZONE", "Europe/Chisinau")),
            send_at=send_at,
            diagnostics_dir=Path(env.get("DIAGNOSTICS_DIR", "diagnostics")),
            state_path=Path(env.get("STATE_PATH", "state/deliveries.sqlite3")),
            github_repository=env.get("GITHUB_REPOSITORY", "TheFirstCookie/benzina"),
            github_token=env.get("GITHUB_TOKEN", "").strip(),
            delivery_branch=env.get("DELIVERY_BRANCH", "bot-deliveries"),
        )

    def require_telegram(self):
        missing = [name for name, value in (("BOT_TOKEN", self.bot_token), ("CHAT_ID", self.chat_id))
                   if not value]
        if missing:
            raise ValueError("Missing Telegram credentials: " + ", ".join(missing))
