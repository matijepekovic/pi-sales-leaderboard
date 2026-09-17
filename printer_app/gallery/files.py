"""Gallery-owned files only. No references to printer attachments, jobs or CUPS."""
from contextlib import contextmanager
import fcntl
import os
import re
import shutil
from pathlib import Path

RESERVE = 512 * 1024 * 1024


class GalleryFiles:
    def __init__(self, root):
        self.root = Path(root)

    def initialize(self):
        if self.root.is_symlink():
            raise ValueError('Gallery root cannot be a symlink')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ('spool', 'crops', 'work'):
            path = self.root / name
            if path.is_symlink():
                raise ValueError('Gallery directories cannot be symlinks')
            path.mkdir(exist_ok=True, mode=0o700)

    @contextmanager
    def lock(self):
        path = self.root / 'files.lock'
        if path.is_symlink():
            raise ValueError('Gallery lock cannot be a symlink')
        with path.open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def temporary_entries(self):
        for category, suffix in (('spool', '.pdf'), ('work', '')):
            for path in (self.root / category).iterdir():
                ident = path.stem if suffix else path.name
                if re.fullmatch(r'[a-f0-9]{64}', ident) and not path.is_symlink():
                    yield category, ident, path.stat().st_mtime

    def prune_partials(self, cutoff):
        for path in (self.root / 'spool').glob('*.partial'):
            if re.fullmatch(r'[a-f0-9]{64}', path.stem) and not path.is_symlink() and path.stat().st_mtime < cutoff:
                path.unlink()

    def path(self, category, ident):
        if category not in ('spool', 'crops', 'work') or not re.fullmatch(r'[a-f0-9]{64}', ident):
            raise ValueError('Invalid gallery file identity')
        suffix = {'spool': '.pdf', 'crops': '.png', 'work': ''}[category]
        parent = self.root / category
        path = parent / (ident + suffix)
        if self.root.is_symlink() or parent.is_symlink() or path.is_symlink():
            raise ValueError('Gallery file symlink refused')
        return path

    def usage(self):
        self.initialize()
        sizes = {}
        for category in ('spool', 'crops', 'work'):
            sizes[category] = sum(p.stat().st_size for p in (self.root / category).rglob('*')
                                  if not p.is_symlink() and p.is_file())
        sizes['database'] = sum(p.stat().st_size for p in self.root.glob('gallery.db*') if p.is_file() and not p.is_symlink())
        sizes['total'] = sum(sizes.values())
        sizes['free'] = shutil.disk_usage(self.root).free
        return sizes

    def require_space(self, amount, max_mb):
        use = self.usage()
        if use['total'] + amount > max_mb * 1048576 or use['free'] < amount + RESERVE:
            raise OSError('Gallery storage limit reached; increase its limit or shorten retention. Printer reserve is protected.')

    def stage(self, ident, payload, max_mb):
        self.initialize()
        target = self.path('spool', ident)
        if target.exists():
            return
        self.require_space(len(payload), max_mb)
        temporary = target.with_suffix('.partial')
        if temporary.is_symlink():
            raise ValueError('Unsafe gallery spool')
        with temporary.open('wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)

    def remove(self, category, ident):
        path = self.path(category, ident)
        if category == 'work' and path.exists():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

    def publish(self, temporary, ident):
        source = Path(temporary)
        if not source.resolve().is_relative_to((self.root / 'work').resolve()) or source.is_symlink():
            raise ValueError('Invalid gallery crop source')
        with source.open('rb') as stream:
            os.fsync(stream.fileno())
        source.replace(self.path('crops', ident))
