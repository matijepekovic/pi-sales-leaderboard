"""Private artifact storage. User-controlled names never select a filesystem path."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile


def safe_name(value):
    name = str(value or 'attachment').replace('\\', '/').rsplit('/', 1)[-1]
    name = re.sub(r'[^\w. -]', '_', name, flags=re.UNICODE).strip(' .')
    stem, suffix = os.path.splitext(name)
    return (stem[:140] or 'attachment') + suffix[:12]


def contained(root: Path, value) -> Path:
    root = root.resolve()
    path = Path(value).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Artifact is outside printer storage')
    return path


def atomic_bytes(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.incoming-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def store_attachment(root, message_key, index, filename, content):
    digest = hashlib.sha256(content).hexdigest()
    bucket = hashlib.sha256(message_key.encode()).hexdigest()
    path = root / 'attachments' / bucket / f'{index}-{digest[:16]}-{safe_name(filename)}'
    atomic_bytes(path, content)
    return path, digest


def check_disk(root, reserve_mb):
    if shutil.disk_usage(root).free < reserve_mb * 1024 * 1024:
        raise OSError('Printer storage is low; email remains unprocessed for automatic retry')
