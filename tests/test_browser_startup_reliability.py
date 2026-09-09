from __future__ import annotations

from profi.browser import BrowserManager


class FakePage:
    def __init__(self, url: str, *, goto_raises: bool = False):
        self.url = url
        self.goto_raises = goto_raises
        self.closed = False

    def goto(self, url, **kwargs):
        if self.goto_raises:
            raise RuntimeError("navigation failed")
        self.url = url

    def close(self, **kwargs):
        self.closed = True

    def is_closed(self):
        return self.closed


class FakeContext:
    def __init__(self, pages):
        self.pages = list(pages)
        self.created = []
        self.new_page_goto_raises = False

    def new_page(self):
        page = FakePage("about:blank", goto_raises=self.new_page_goto_raises)
        self.pages.append(page)
        self.created.append(page)
        return page


def test_feed_start_reuses_existing_blank_instead_of_creating_another(monkeypatch):
    blank = FakePage("about:blank")
    ctx = FakeContext([blank])
    bm = BrowserManager()

    page = bm._ensure_feed_page(ctx)  # noqa: SLF001

    assert page is blank
    assert ctx.created == []
    assert page.url == "https://profi.ru/backoffice/n.php"


def test_failed_navigation_closes_only_new_provisional_page(monkeypatch):
    ctx = FakeContext([])
    ctx.new_page_goto_raises = True
    bm = BrowserManager()

    page = bm._ensure_feed_page(ctx)  # noqa: SLF001

    assert page is None
    assert len(ctx.created) == 1
    assert ctx.created[0].closed is True


def test_failed_navigation_does_not_close_reused_user_blank(monkeypatch):
    blank = FakePage("about:blank", goto_raises=True)
    ctx = FakeContext([blank])
    bm = BrowserManager()

    page = bm._ensure_feed_page(ctx)  # noqa: SLF001

    assert page is blank
    assert blank.closed is False
    assert ctx.created == []
