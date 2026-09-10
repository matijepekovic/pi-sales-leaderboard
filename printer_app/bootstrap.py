"""This second application's sole composition root. No host-app imports."""
from .config import Config
from .db import migrate
from .repository import Repository


def build_web(config=None):
    from .services import ControlService
    from .web import create_app
    config = config or Config.load()
    migrate(config.database)
    repository = Repository(config.database)
    return create_app(config, ControlService(config, repository))


def build_worker(config=None):
    from .converter import LibreOfficeRenderer
    from .gmail_client import GmailClient
    from .printer import CupsPrinter
    from .services import PrintService
    from .worker import Worker
    config = config or Config.load()
    migrate(config.database)
    repository = Repository(config.database)
    printing = PrintService(config, repository, LibreOfficeRenderer(config.conversion_timeout), CupsPrinter(config.queue))
    return Worker(config, repository, GmailClient(config), printing)
