"""Delete only application-owned output directories; never follow a symlink."""
from pathlib import Path
import re
import shutil


class RetentionFiles:
    def __init__(self, data_dir: Path):
        self.root = data_dir.resolve()

    def remove(self, category: str, ident: int):
        if category not in ('jobs', 'attachments') or type(ident) is not int or ident < 1:
            raise ValueError('Invalid cleanup file identity')
        parent = self.root / category
        target = parent / str(ident)
        if parent.is_symlink() or target.is_symlink():
            raise OSError('Refusing symlink in cleanup path')
        if not target.resolve().is_relative_to(self.root):
            raise OSError('Cleanup path outside printer storage')
        if target.exists():
            shutil.rmtree(target)  # Linux fd-based rmtree does not follow children.

    def prune_backups(self, cutoff):
        directory = self.root / 'backups'
        if directory.is_symlink():
            raise OSError('Refusing symlink in backup path')
        if not directory.exists():
            return 0
        count = 0
        for path in directory.iterdir():
            if (re.fullmatch(r'printer-app-\d{8}-\d{6}\.db', path.name)
                    and not path.is_symlink() and path.is_file()
                    and path.stat().st_mtime < cutoff):
                path.unlink()
                count += 1
        return count
