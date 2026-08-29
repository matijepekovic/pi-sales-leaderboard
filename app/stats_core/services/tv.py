"""TV/display control service.

OS-specific behavior is supplied by the platform object; route handlers no
longer know how Windows/Linux launch or restart the display.
"""
from __future__ import annotations


class TvService:
    def __init__(self, repos, platform):
        self.repos = repos
        self.platform = platform

    def report_geometry(self, width, height):
        try:
            width = int(float(width or 0))
            height = int(float(height or 0))
        except (TypeError, ValueError):
            width = height = 0
        if not (320 <= width <= 16384 and 240 <= height <= 16384):
            raise ValueError("Unusable viewport size.")
        self.repos.meta.set("tv_viewport_w", width)
        self.repos.meta.set("tv_viewport_h", height)
        import time
        self.repos.meta.set("tv_viewport_seen", time.strftime("%Y-%m-%d %H:%M:%S"))
        return {"w": width, "h": height}

    def geometry(self):
        width = int(self.repos.meta.get("tv_viewport_w", "0") or 0)
        height = int(self.repos.meta.get("tv_viewport_h", "0") or 0)
        source = "kiosk"
        if not (width and height):
            width, height = self.platform.native_display_mode()
            source = self.platform.native_display_source
        if not (width and height):
            width, height, source = 1920, 1080, "default"
        return {
            "width": width,
            "height": height,
            "aspect": round(width / height, 6) if height else 16 / 9,
            "source": source,
            "seen_at": self.repos.meta.get("tv_viewport_seen", ""),
        }

    def refresh(self):
        return self.repos.meta.bump("tv_refresh_version")

    def fullscreen(self):
        self.platform.request_fullscreen()
        return {
            "message": "TV fullscreen relaunch requested.",
            "startup_status": self.repos.meta.get("kiosk_startup_status", ""),
        }

    def restart(self):
        restart_version = self.repos.meta.bump("app_restart_version")
        self.repos.meta.bump("tv_refresh_version")
        self.platform.restart_application(delay_seconds=1.2)
        return {
            "message": "Leaderboard app is restarting.",
            "app_restart_version": restart_version,
        }
