"""Low-priority gallery processing lifecycle. Never opens Gmail or a printer queue."""
import fcntl
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

from ..config import Config, environment_file
from ..settings import SettingsService
from ..settings_repository import SettingsRepository
from .bootstrap import build

log = logging.getLogger(__name__)


def saved_image_reader(gallery, stop):
    """Isolated, bounded OCR adapter used only by the gallery worker."""
    def read(path):
        if stop.is_set() or not path.is_file():
            raise ValueError('Image unavailable for recognition')
        if gallery.files.usage()['free'] < 576 * 1048576:
            raise ValueError('Waiting for recognition workspace')
        directory = gallery.files.path('work', path.stem)
        gallery.files.remove('work', path.stem)
        directory.mkdir()
        try:
            env = {'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8', 'OMP_THREAD_LIMIT':'1',
                   'OPENBLAS_NUM_THREADS':'1', 'PYTHONDONTWRITEBYTECODE':'1'}
            script = Path(__file__).with_name('recognition.py')
            with subprocess.Popen(['/usr/bin/python3',str(script),str(path),str(directory)],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as child:
                deadline = time.monotonic()+150
                while child.poll() is None:
                    if stop.wait(2) or time.monotonic() > deadline:
                        child.terminate()
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            child.kill()
                        break
                    gallery.repository.set_state(dict(heartbeat=time.time(),processing=False,
                        repairing=True,error=''))
                if child.wait() != 0 or stop.is_set():
                    raise ValueError('Recognition will retry later')
            result = directory / 'recognition.json'
            if result.stat().st_size > 1000000:
                raise ValueError('Recognition response too large')
            return json.loads(result.read_text(encoding='utf-8'))
        finally:
            gallery.files.remove('work', path.stem)
    return read


def main():
    logging.basicConfig(level=logging.INFO)
    os.umask(0o077)
    cfg = Config.from_env()
    settings = SettingsService(SettingsRepository(cfg.env_file or environment_file()), cfg)
    gallery = build(cfg.data_dir)
    gallery.initialize()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    with (gallery.files.root / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        gallery.repository.recover()
        gallery.clear_temporary()
        next_cleanup = 0
        read_saved = saved_image_reader(gallery, stop)
        while not stop.is_set():
            job = None
            try:
                cfg, _ = settings.read()
                now = time.time()
                state = dict(heartbeat=now, error='', processing=False)
                gallery.repository.set_state(state)
                if now >= next_cleanup:
                    gallery.expire(cfg.gallery.days, cfg.timezone)
                    gallery.clear_temporary()
                    next_cleanup = now + 3600
                job = gallery.repository.claim()
                if job:
                    use = gallery.files.usage()
                    budget = min(cfg.gallery.max_mb * 1048576 - use['total'], use['free'] - 576 * 1048576)
                    if budget < 32 * 1048576:
                        gallery.repository.failed(job['id'], 'Waiting for gallery space; printing is unaffected.', retry=True)
                        stop.wait(60)
                        continue
                    directory = gallery.files.path('work', job['id'])
                    gallery.files.remove('work', job['id'])
                    directory.mkdir()
                    script = Path(__file__).with_name('processing.py')
                    # Distro image/OCR dependencies are independent of the printer venv.
                    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'OMP_THREAD_LIMIT': '1',
                           'OPENBLAS_NUM_THREADS': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
                    with subprocess.Popen(['/usr/bin/python3', str(script), str(gallery.files.path('spool', job['id'])),
                            str(directory), str(budget)], env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL) as child:
                        deadline = time.monotonic() + 1800
                        while child.poll() is None:
                            if stop.wait(5) or time.monotonic() > deadline:
                                child.terminate()
                                try:
                                    child.wait(timeout=10)
                                except subprocess.TimeoutExpired:
                                    child.kill()
                                break
                            gallery.repository.set_state(dict(heartbeat=time.time(), processing=True, error=''))
                            gallery.report_progress(job['id'])
                        if stop.is_set():
                            gallery.repository.failed(job['id'], 'Interrupted; will resume after restart.', retry=True)
                            break
                        if child.wait() != 0:
                            raise ValueError('Import failed: unreadable PDF, unsupported layout, missing local tools, or storage limit. Resend after correcting it.')
                    gallery.report_progress(job['id'])
                    manifest = json.loads((directory / 'manifest.json').read_text())
                    gallery.publish(job, manifest, directory)
                    # Newly imported old documents follow the printed-date policy too.
                    gallery.expire(cfg.gallery.days, cfg.timezone)
                    log.info('Gallery import complete: %s crop(s)', len(manifest['items']))
                # One repair per iteration, after any new import. Printing has a
                # different service; neither imports nor repairs run in web requests.
                repaired = False if stop.is_set() else gallery.repair_one(read_saved)
                if not job and not repaired:
                    stop.wait(5)
            except Exception as exc:
                log.warning('Gallery task failed: %s', type(exc).__name__)
                if job and gallery.repository.import_state(job['id']) != 'COMPLETE':
                    with gallery.files.lock():
                        gallery.repository.failed(job['id'], 'Import failed; source discarded. Check tools/storage and resend PDF.')
                        gallery.files.remove('spool', job['id'])
                        gallery.files.remove('work', job['id'])
                gallery.repository.set_state(dict(heartbeat=time.time(), processing=False,
                    error='Gallery import failed. Printing is unaffected. Check recent imports and gallery logs.'))
                stop.wait(15)
        gallery.repository.set_state(dict(heartbeat=0, processing=False, error='Gallery worker stopped'))


if __name__ == '__main__':
    main()
