"""BrowserManager: жизненный цикл Chrome + CDP (спека разд. 5–7)."""
from profi.browser.manager import (
    AUTH_REQUIRED,
    BROWSER_OFFLINE,
    PROFI_UNAVAILABLE,
    READY,
    BrowserManager,
    is_feed_url,
)

__all__ = [
    "AUTH_REQUIRED",
    "BROWSER_OFFLINE",
    "BrowserManager",
    "PROFI_UNAVAILABLE",
    "READY",
    "is_feed_url",
]
