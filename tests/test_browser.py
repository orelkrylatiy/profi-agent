"""is_feed_url: распознавание вкладки ленты vs открытого заказа (browser, спека разд. 6)."""

import pytest

from profi.browser import is_feed_url


@pytest.mark.parametrize(
    "url",
    [
        "https://profi.ru/backoffice/n.php",
        "https://profi.ru/backoffice/n.php?sort=fresh",
        "http://profi.ru/backoffice/n.php",
        "https://sub.profi.ru/backoffice/n.php",  # поддомен допускается
    ],
)
def test_feed_urls(url):
    assert is_feed_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://profi.ru/backoffice/n.php?o=12345",  # открытый заказ, не лента
        "https://profi.ru/backoffice/r.php",  # чаты
        "https://example.com/backoffice/n.php",  # чужой хост
        "about:blank",
        "",
    ],
)
def test_not_feed_urls(url):
    assert not is_feed_url(url)


def test_query_param_lookalike_is_feed():
    # ?logo=1 содержит подстроку "o=", но параметра o нет — это лента (ревью P3)
    assert is_feed_url("https://profi.ru/backoffice/n.php?logo=1")


class TestOrderTab:
    def test_order_tabs(self):
        from profi.browser import is_order_tab

        assert is_order_tab("https://profi.ru/backoffice/n.php?o=93369206")
        assert is_order_tab(
            "https://profi.ru/backoffice/n.php?o=93451714&analytics_data=%7B%22source%22%7D"
        )
        assert not is_order_tab("https://profi.ru/backoffice/n.php")  # лента
        assert not is_order_tab("https://profi.ru/backoffice/r.php?filter=open")
        assert not is_order_tab("https://example.com/backoffice/n.php?o=1")


class TestStrayTabsHygiene:
    """close_stray_tabs: дубликаты ленты и зависшие карточки закрываются."""

    class FakePage:
        def __init__(self, url):
            self.url = url
            self.closed = False

        def close(self, **kw):
            self.closed = True

    class FakeCtx:
        def __init__(self, pages):
            self.pages = pages

    def _manager(self, pages):
        from profi.browser import BrowserManager

        bm = BrowserManager()
        bm.browser = object()  # не None — ensure_ready не выйдет сразу
        bm._default_context = lambda: self.FakeCtx(pages)  # noqa: SLF001
        return bm

    def test_closes_duplicates_and_order_tabs(self):
        feed1 = self.FakePage("https://profi.ru/backoffice/n.php")
        feed2 = self.FakePage("https://profi.ru/backoffice/n.php?sort=fresh")
        order = self.FakePage("https://profi.ru/backoffice/n.php?o=123")
        chats = self.FakePage("https://profi.ru/backoffice/r.php")
        bm = self._manager([feed1, order, feed2, chats])
        closed = bm.close_stray_tabs()
        assert not feed1.closed  # первая лента жива
        assert feed2.closed and order.closed
        assert not chats.closed  # чужие вкладки не трогаем
        assert len(closed) == 2
