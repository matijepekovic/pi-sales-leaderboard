"""Small, application-owned contracts at the mail, renderer and printer boundaries."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Protocol, Any


@dataclass(frozen=True)
class Attachment:
    filename: str
    path: Path
    sha256: str
    size: int


@dataclass(frozen=True)
class Message:
    source_key: str
    scope: str
    uid: str
    uid_validity: str
    message_id: str
    subject: str
    sender: str
    attachments: tuple[Attachment, ...]


@dataclass(frozen=True)
class Cell:
    value: Any
    number_format: str = "General"


@dataclass(frozen=True)
class ReportGroup:
    key: str
    substatus: str
    headers: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]
    sheet: str


@dataclass(frozen=True)
class Submission:
    request_id: str = ""
    detail: str = ""
    uncertain: bool = False


class MailSource(Protocol):
    def messages(self, already_seen: Callable[[str], bool]) -> Iterable[Message]: ...


class Renderer(Protocol):
    def render(self, group: ReportGroup, directory: Path) -> tuple[Path, Path]: ...


class Printer(Protocol):
    def snapshot(self) -> dict: ...
    def submit(self, path: Path, token: str, tabloid: bool) -> Submission: ...
    def find(self, token: str) -> str | None: ...
    def state(self, request_id: str) -> str: ...
