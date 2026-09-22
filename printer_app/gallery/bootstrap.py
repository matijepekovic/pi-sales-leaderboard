"""The gallery composition boundary. Heavy image libraries stay out of web/printing."""
from .access_repository import GalleryAccessRepository
from .access_service import GalleryAccessService
from .files import GalleryFiles
from .repository import GalleryRepository
from .service import GalleryService
from .policy import GalleryOptions


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

    def __init__(self, data_dir, options=None):
        self.service = build(data_dir)
        self.options = options or GalleryOptions()

    def publish(self, day, kind, records, captured, *, pdf_payload=None):
        result = self.service.publish_reference_snapshot(day, kind, records, captured)
        if kind == 'morning' and pdf_payload is not None:
            self.service.offer_morning(day, f'MOD-Sheet-{day}.pdf', pdf_payload, self.options)
        return result

    def dates(self):
        return self.service.reference_dates()

    def repair_missing_work_orders(self):
        return self.service.repair_missing_work_orders()

    def work_order_numbers(self, *, missing_only=False):
        return self.service.work_order_numbers(missing_only=missing_only)

    def work_order_lookup_numbers(self):
        return self.service.work_order_lookup_numbers()

    def publish_lead_statuses(self, work_order_numbers, records, captured, *, missing_only=False):
        return self.service.publish_lead_statuses(work_order_numbers, records, captured, missing_only=missing_only)

    def publish_work_order_records(self, work_order_numbers, records, captured):
        return self.service.publish_work_order_records(work_order_numbers, records, captured)
