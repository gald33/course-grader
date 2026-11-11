from __future__ import annotations

import httpx

from app.services.link_check import check_link


def _site(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))

    return httpx.MockTransport(handler)


def _check(url, routes):
    return check_link(url, transport=_site(routes), require_public=False)


HTML = {"content-type": "text/html; charset=utf-8"}


def test_a_live_page_is_ok_even_after_redirects():
    routes = {
        "https://jokes.example.org/": httpx.Response(301, headers={"location": "https://jokes.example.org/he/"}),
        "https://jokes.example.org/he/": httpx.Response(200, headers=HTML, text="<h1>בדיחה</h1>"),
    }
    result = _check("https://jokes.example.org/", routes)
    assert (result.status, result.final_url) == ("ok", "https://jokes.example.org/he/")


def test_links_that_are_not_a_live_site_are_flagged():
    assert _check("https://github.com/team/jokes", {}).status == "warning"
    assert "שיחה" in _check("https://chatgpt.com/share/abc", {}).detail
    assert _check("https://drive.google.com/file/d/x/view", {}).status == "warning"
    # GitHub Pages is a real site and is fetched normally.
    assert _check("https://team.github.io/jokes/", {"https://team.github.io/jokes/": httpx.Response(200, headers=HTML)}).status == "ok"
    # Redirecting to code counts too.
    moved = {"https://t.ly/x": httpx.Response(302, headers={"location": "https://github.com/team/jokes"})}
    assert _check("https://t.ly/x", moved).status == "warning"


def test_broken_login_walled_and_download_links():
    assert _check("https://gone.example.org/", {}).status == "broken"  # 404
    assert _check("ftp://x.org/", {}).status == "broken"
    assert _check("jokes.example.org", {}).status == "broken"
    walled = {"https://a.example.org/": httpx.Response(403)}
    assert _check("https://a.example.org/", walled).status == "warning"
    download = {"https://b.example.org/site.zip": httpx.Response(200, headers={"content-type": "application/zip"})}
    assert _check("https://b.example.org/site.zip", download).status == "warning"

    def boom(request):
        raise httpx.ConnectError("refused")

    down = check_link("https://down.example.org/", transport=httpx.MockTransport(boom), require_public=False)
    assert down.status == "broken"


def test_local_and_private_addresses_are_never_fetched():
    for url in ("http://localhost:3000/", "http://127.0.0.1:5500/index.html", "http://192.168.1.10/", "http://169.254.169.254/latest"):
        result = check_link(url)
        assert result.status == "broken", url


def test_private_links_do_not_initialize_networking(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("Private links must not initialize a network client")

    monkeypatch.setattr(httpx, "Client", unexpected_client)
    for url in ("http://localhost/", "http://127.0.0.1/", "http://192.168.1.10/"):
        assert check_link(url).status == "broken"
