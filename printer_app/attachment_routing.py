"""Pure attachment routing. No mail server, database, image tools or printer calls."""
from dataclasses import dataclass
from typing import Protocol

from .gallery.policy import GalleryOptions


class PdfConsumer(Protocol):
    def offer(self, filename: str, payload: bytes) -> None:
        """Return only after the consumer durably owns the PDF; raise to retry."""
        ...


@dataclass(frozen=True)
class AttachmentRoute:
    print_document: bool
    import_document: bool


@dataclass(frozen=True)
class AttachmentRouter:
    print_subject: str
    print_sender: str
    gallery: GalleryOptions

    def snapshot(self) -> dict:
        # Only routing selectors, never credentials, storage settings or timestamps.
        return dict(print_subject=self.print_subject, print_sender=self.print_sender,
                    gallery={k: getattr(self.gallery, k) for k in
                             ('enabled', 'subject', 'sender', 'filename', 'print_mode')})

    @classmethod
    def restore(cls, value: dict) -> 'AttachmentRouter':
        return cls(value['print_subject'], value['print_sender'], GalleryOptions(**value['gallery']))

    def print_matches(self, subject: str, sender: str) -> bool:
        return (self.print_subject.casefold() in subject.casefold()
                and self.print_sender.casefold() in sender.casefold())

    def gallery_candidate(self, subject: str, sender: str) -> bool:
        return self.gallery.matches(subject, sender)

    def attachment(self, subject: str, sender: str, filename: str) -> AttachmentRoute:
        to_gallery = self.gallery.matches_pdf(subject, sender, filename)
        to_print = self.print_matches(subject, sender)
        if to_gallery and self.gallery.print_mode == 'gallery-only':
            to_print = False
        return AttachmentRoute(to_print, to_gallery)

    def unreadable_message(self, subject: str, sender: str) -> AttachmentRoute:
        # Filenames cannot be trusted without MIME structure. A possible gallery-only
        # message must wait for inspection, not emit an unsolicited print/error sheet.
        candidate = self.gallery_candidate(subject, sender)
        to_print = self.print_matches(subject, sender)
        if candidate and self.gallery.print_mode == 'gallery-only':
            to_print = False
        return AttachmentRoute(to_print, candidate)
