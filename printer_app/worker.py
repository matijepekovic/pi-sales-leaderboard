"""Dedicated, single-owner worker process. Does not import or run any web server."""
import fcntl
import logging
import signal
import threading
import time

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, config, repository, mail, printing):
        self.config, self.repo, self.mail, self.printing = config, repository, mail, printing
        self.stop = threading.Event()
        self.next_check = 0.0

    def poll(self):
        checked = time.time()
        log.info('Inbox polling')
        self.repo.put('monitor', {'state': 'checking', 'last_check': checked, 'next_check': None, 'gmail': 'connecting'})
        try:
            for message in self.mail.messages(self.repo.seen):
                self.repo.ingest(message)
            status = {'state': 'running', 'gmail': 'connected'}
        except Exception as exc:
            # IMAP exceptions can contain server-supplied text. Do not log credential-bearing details.
            status = {'state': 'error', 'gmail': 'disconnected', 'error': 'Gmail check failed: ' + type(exc).__name__}
            log.warning('Gmail check failed: %s', type(exc).__name__)
        self.next_check = time.time() + self.config.poll_seconds
        self.repo.put('monitor', status | {'last_check': checked, 'next_check': self.next_check})

    def tick(self):
        paused = self.repo.get('paused', False)
        commands = self.repo.commands()
        run_now = any(c['kind'] == 'run' for c in commands)
        for command in commands:
            if command['kind'] == 'test':
                self.printing.test_print(command['id'])
                self.repo.acknowledge(command['id'])
        if run_now or (not paused and time.time() >= self.next_check):
            self.poll()
            for command in commands:
                if command['kind'] == 'run':
                    self.repo.acknowledge(command['id'])
        if not paused or run_now:
            self.printing.prepare()
        # Test Print is an explicit one-shot, including while the monitor is paused.
        self.printing.dispatch(allow_new=not paused or run_now or any(c['kind'] == 'test' for c in commands))
        try:
            self.repo.put('printer', self.printing.printer.snapshot())
        except Exception as exc:
            self.repo.put('printer', {'queue': self.config.queue, 'known': False, 'online': False, 'detail': 'CUPS unavailable: ' + type(exc).__name__})

    def run(self):
        lock_path = self.config.data_dir / 'worker.lock'
        with lock_path.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('A printer worker already owns this data directory') from exc
            for name in (signal.SIGTERM, signal.SIGINT):
                signal.signal(name, lambda *_: self.stop.set())
            def heartbeat():
                while not self.stop.is_set():
                    try:
                        self.repo.put('heartbeat', time.time())
                    except Exception:
                        log.error('Worker heartbeat could not reach its database')
                    self.stop.wait(5)
            thread = threading.Thread(target=heartbeat, name='printer-heartbeat', daemon=True)
            thread.start()
            try:
                while not self.stop.is_set():
                    try:
                        self.tick()
                    except Exception as exc:
                        self.repo.put('monitor', {'state': 'error', 'error': 'Worker cycle failed: ' + type(exc).__name__})
                        log.error('Worker cycle failed: %s', type(exc).__name__)
                    self.stop.wait(2)
            finally:
                self.stop.set()
                thread.join(timeout=6)
                self.repo.put('heartbeat', 0)
