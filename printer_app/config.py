"""Printer-owned configuration; never reads the host application's settings."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    data_dir: Path
    email_user: str = ""
    email_password: str = ""
    mailbox: str = "INBOX"
    subject_contains: str = ""
    from_contains: str = ""
    lookback_days: int = 1
    poll_seconds: int = 60
    attachment_warn_mb: int = 25
    disk_reserve_mb: int = 128
    conversion_timeout: int = 90
    queue: str = "konicaa"
    host: str = "0.0.0.0"
    port: int = 5055
    ui_user: str = "admin"
    ui_password_hash: str = ""
    session_secret: str = ""
    secure_cookie: bool = False

    @property
    def database(self) -> Path:
        return self.data_dir / "printer_app.db"

    @classmethod
    def load(cls):
        env_file = Path(os.environ.get("PRINTER_ENV", str(Path.home() / ".config/printer-app/env")))
        load_dotenv(env_file, override=False, interpolate=False)
        def number(name, default, minimum=1):
            result = int(os.environ.get(name, default))
            if result < minimum:
                raise ValueError(f"{name} must be at least {minimum}")
            return result
        queue = os.environ.get("PRINTER_QUEUE", "konicaa")
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", queue):
            raise ValueError("Invalid PRINTER_QUEUE")
        return cls(
            data_dir=Path(os.environ.get("PRINTER_DATA_DIR", str(Path.home() / ".local/share/printer-app/data"))).expanduser().resolve(),
            email_user=os.environ.get("EMAIL_USER", ""),
            email_password=os.environ.get("EMAIL_APP_PASSWORD", ""),
            mailbox=os.environ.get("EMAIL_MAILBOX", "INBOX"),
            subject_contains=os.environ.get("EMAIL_SUBJECT_CONTAINS", ""),
            from_contains=os.environ.get("EMAIL_FROM_CONTAINS", ""),
            lookback_days=number("EMAIL_LOOKBACK_DAYS", 1),
            poll_seconds=number("EMAIL_POLL_SECONDS", 60, 10),
            attachment_warn_mb=number("ATTACHMENT_WARN_MB", 25),
            disk_reserve_mb=number("DISK_RESERVE_MB", 128, 0),
            conversion_timeout=number("CONVERSION_TIMEOUT_SECONDS", 90),
            queue=queue, host=os.environ.get("PRINTER_HOST", "0.0.0.0"),
            port=number("PRINTER_PORT", 5055), ui_user=os.environ.get("UI_USER", "admin"),
            ui_password_hash=os.environ.get("UI_PASSWORD_HASH", ""),
            session_secret=os.environ.get("SESSION_SECRET", ""),
            secure_cookie=os.environ.get("COOKIE_SECURE", "0") == "1",
        )
