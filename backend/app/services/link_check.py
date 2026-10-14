"""Check that a team's link opens a working website for someone else.

The jokes-site homework says a link to code, a chat or a file download is not
a link to a live site, and that the site must work without the team's
computer. This check catches those cases before reviewers open the link:

  ok      - the page loaded (HTTP < 400, an HTML page)
  warning - it loaded but looks like something other than a public site
            (sign-in wall, code repository, chat, file, not an HTML page)
  broken  - it doesn't open (bad address, private/local address, error, timeout)

Only public addresses are fetched: every hop (including redirects) is
resolved and refused if it points at a private, loopback or link-local IP, so
students can't use the server to reach internal services.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

TIMEOUT_SECONDS = 8.0
MAX_REDIRECTS = 5
USER_AGENT = "Mozilla/5.0 (compatible; course-grader link check)"

# (pattern on host+path, message). Checked before fetching: these open fine
# but aren't the team's site.
NOT_A_SITE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(www\.)?github\.com/"), "זה קישור לקוד ב-GitHub, לא לאתר פעיל (אפשר לפרסם אותו, למשל ב-GitHub Pages)"),
    (re.compile(r"^(www\.)?gitlab\.com/"), "זה קישור לקוד, לא לאתר פעיל"),
    (re.compile(r"^(chatgpt\.com|chat\.openai\.com)/"), "זה קישור לשיחה עם צ׳טבוט, לא לאתר פעיל"),
    (re.compile(r"^claude\.ai/"), "זה קישור לשיחה עם צ׳טבוט, לא לאתר פעיל"),
    (re.compile(r"^(gemini\.google\.com|g\.co/gemini)/"), "זה קישור לשיחה עם צ׳טבוט, לא לאתר פעיל"),
    (re.compile(r"^(drive|docs)\.google\.com/"), "זה קישור לקובץ ב-Google Drive, לא לאתר פעיל"),
    (re.compile(r"^colab\.research\.google\.com/"), "זה קישור למחברת Colab, לא לאתר פעיל"),
    (re.compile(r"^(www\.)?dropbox\.com/"), "זה קישור להורדת קובץ, לא לאתר פעיל"),
    (re.compile(r"^(1drv\.ms|onedrive\.live\.com)/"), "זה קישור לקובץ, לא לאתר פעיל"),
]


@dataclass
class LinkCheck:
    status: str  # ok | warning | broken
    detail: str  # Hebrew, shown to students and the instructor
    final_url: str = ""


class _Refused(Exception):
    pass


def _public_host(host: str) -> None:
    if not host:
        raise _Refused("כתובת לא תקינה")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise _Refused("זו כתובת שעובדת רק במחשב שלכם")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise _Refused("הכתובת לא קיימת (שם האתר לא נמצא)")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise _Refused("זו כתובת פרטית שעובדת רק אצלכם, לא קישור ציבורי")


def _not_a_site(url: str) -> str | None:
    parts = urlsplit(url)
    target = f"{(parts.hostname or '').lower()}{parts.path or '/'}"
    for pattern, message in NOT_A_SITE:
        if pattern.match(target):
            return message
    return None


def check_link(url: str, transport: httpx.BaseTransport | None = None, require_public: bool = True) -> LinkCheck:
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return LinkCheck("broken", "הקישור צריך להתחיל ב-https://")
    message = _not_a_site(url)
    if message:
        return LinkCheck("warning", message, url)

    current = url
    try:
        with httpx.Client(
            transport=transport, timeout=TIMEOUT_SECONDS, follow_redirects=False, headers={"User-Agent": USER_AGENT}
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                if require_public:
                    _public_host(urlsplit(current).hostname or "")
                with client.stream("GET", current) as res:
                    if res.is_redirect and "location" in res.headers:
                        current = str(res.url.join(res.headers["location"]))
                        if urlsplit(current).scheme not in ("http", "https"):
                            return LinkCheck("broken", "הקישור מפנה לכתובת לא תקינה", current)
                        message = _not_a_site(current)
                        if message:
                            return LinkCheck("warning", message, current)
                        continue
                    status = res.status_code
                    ctype = res.headers.get("content-type", "").lower()
                    disposition = res.headers.get("content-disposition", "").lower()
                    break
            else:
                return LinkCheck("broken", "הקישור מפנה שוב ושוב בלי להגיע לדף", current)
    except _Refused as exc:
        return LinkCheck("broken", str(exc), current)
    except httpx.TimeoutException:
        return LinkCheck("broken", "האתר לא ענה בזמן (ייתכן שהוא כבוי או איטי מאוד)", current)
    except httpx.HTTPError:
        return LinkCheck("broken", "לא הצלחנו להתחבר לאתר", current)

    if status in (401, 403):
        return LinkCheck("warning", "האתר דורש התחברות או חוסם גישה – בדקו שהוא פתוח לכולם", current)
    if status == 404:
        return LinkCheck("broken", "הדף לא נמצא (שגיאה 404)", current)
    if status >= 400:
        return LinkCheck("broken", f"האתר החזיר שגיאה ({status})", current)
    if "attachment" in disposition:
        return LinkCheck("warning", "הקישור מוריד קובץ במקום לפתוח אתר", current)
    if ctype and "html" not in ctype:
        return LinkCheck("warning", "הקישור נפתח, אבל זה לא דף אינטרנט (HTML)", current)
    host = (urlsplit(current).hostname or "").lower()
    if host.endswith(("accounts.google.com", "login.microsoftonline.com")) or "/login" in urlsplit(current).path.lower():
        return LinkCheck("warning", "הקישור מפנה לדף התחברות – בדקו שהאתר פתוח לכולם", current)
    return LinkCheck("ok", "האתר נפתח", current)
