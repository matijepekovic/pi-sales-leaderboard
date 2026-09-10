"""Child-process environment policy, shared by the CUPS and office adapters."""
import os


def safe_environment() -> dict[str, str]:
    # Child processes do not receive Gmail credentials, the session key or UI hashes.
    allowed = {'PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'TMPDIR', 'XDG_RUNTIME_DIR'}
    return {key: value for key, value in os.environ.items() if key in allowed} | {'LC_ALL': 'C'}
