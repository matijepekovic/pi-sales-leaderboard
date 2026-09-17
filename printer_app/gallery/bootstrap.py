"""The gallery composition boundary. Heavy image libraries stay out of web/printing."""
from .files import GalleryFiles
from .repository import GalleryRepository
from .service import GalleryService


def build(data_dir):
    root = data_dir / 'gallery'
    return GalleryService(GalleryRepository(root / 'gallery.db'), GalleryFiles(root))


class GalleryInbox:
    """Optional normalized PDF consumer for the existing email adapter."""
    def __init__(self, data_dir, options):
        self.options = options
        self.service = build(data_dir)

    def matches(self, subject, sender):
        return self.options.matches(subject, sender)

    def offer(self, filename, payload):
        self.service.offer(filename, payload, self.options)
