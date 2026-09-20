"""The gallery composition boundary. Heavy image libraries stay out of web/printing."""
from .access_repository import GalleryAccessRepository
from .access_service import GalleryAccessService
from .files import GalleryFiles
from .repository import GalleryRepository
from .service import GalleryService


def build_access(data_dir):
    root = data_dir / 'gallery'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return GalleryAccessService(GalleryAccessRepository(root / 'gallery.db'))


def build(data_dir):
    root = data_dir / 'gallery'
    return GalleryService(GalleryRepository(root / 'gallery.db'), GalleryFiles(root))


class GalleryInbox:
    """Optional normalized PDF consumer for the existing email adapter."""
    def __init__(self, data_dir, options):
        self.options = options
        self.service = build(data_dir)

    def offer(self, filename, payload):
        self.service.offer(filename, payload, self.options)


class GalleryReferenceInbox:
    """Optional normalized appointment-reference sink for Gallery enrichment."""

    def __init__(self, data_dir):
        self.service = build(data_dir)

    def publish(self, day, kind, records, captured):
        return self.service.publish_reference_snapshot(day, kind, records, captured)
