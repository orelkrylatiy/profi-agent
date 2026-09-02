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
