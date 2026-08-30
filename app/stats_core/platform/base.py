"""What the application requires of the machine it is running on.

Everything the core needs from an operating system is named here, so a second
platform can be written against this file instead of against Windows. Nothing in
this module imports an OS-specific thing -- that is the whole point of it.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Platform(Protocol):
    """The host-specific half of the application."""

    #: Reported by /api/tv/geometry so the display knows who measured it.
    native_display_source: str

    #: Endpoints this platform adds that survive the settings PIN lock.
    #: Declared, not discovered, so the allowlist is complete before anything
    #: is registered.
    public_endpoints: frozenset

    def native_display_mode(self) -> tuple:
        """Return the primary display's (width, height), or (0, 0) if unknown."""

    def request_fullscreen(self) -> None:
        """Ask the host shell to put the display back into fullscreen."""

    def restart_application(self, delay_seconds: float = 1.2) -> None:
        """Exit so the host supervisor restarts the server."""

    def update_channel(self) -> dict:
        """Describe the update mechanism for /api/github/status."""

    def apply_source_update(self) -> tuple:
        """Handle a source-ZIP update request: (payload, http_status)."""

    def register(self, app, public_endpoints) -> None:
        """Install host-specific routes and record host-specific state."""

    def start_remote_qr_refresh(self) -> None:
        """Begin publishing the phone-access QR code, if the host offers one."""
