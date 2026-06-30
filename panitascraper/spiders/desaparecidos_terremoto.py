"""
DesaparecidosTerremotoSpider — paginated JSON API spider for
desaparecidosterremotovenezuela.com (backend: desaparecidos-terremoto-api.theempire.tech).

The API requires a valid reCAPTCHA v3 token on every request (header: x-recaptcha-token).
Strategy: use Playwright once to load the real site and call grecaptcha.execute() to
obtain a fresh token; then use regular HTTP for all ~600 paginated API requests,
refreshing the token via Playwright every TOKEN_TTL seconds before it expires.

API endpoint: GET /api/personas?page=<n>&pageSize=<size>
Response: {
    "items": [...],
    "total": 59914,
    "page": 1,
    "pageSize": 100,
    "totalPages": ~600,
    "counts": { "registrosTotales", "personasUnicas", "sinContacto", "localizado" }
}

Estados: sin-contacto, localizado.
"""

import json
import logging
import time
from typing import AsyncIterator, Generator
from urllib.parse import urlencode

import scrapy
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

API_BASE = "https://desaparecidos-terremoto-api.theempire.tech/api/personas"
SITE_URL = "https://desaparecidosterremotovenezuela.com/"
RECAPTCHA_SITE_KEY = "6LeBfDUtAAAAAMw1Wtkd58bst6vEnLOi3_NAjGD0"
PAGE_SIZE = 100
TOKEN_TTL = 90  # reCAPTCHA v3 tokens expire in ~2 min; refresh every 90s to be safe


def _build_url(page: int) -> str:
    return f"{API_BASE}?{urlencode({'page': page, 'pageSize': PAGE_SIZE})}"


class DesaparecidosTerremotoSpider(BaseSpider):
    name = "desaparecidos_terremoto"
    field_map = {
        "nombre":       "nombre",
        "cedula":       "cedula",
        "edad":         "edad",
        "hospital":     "ubicacion",
        "ciudad":       "ciudad",
        "tipo_reporte": "estado",
        "condicion":    "condicion",
        "estado":       "estado",
        "notas":        "descripcion",
    }

    allowed_domains = [
        "desaparecidos-terremoto-api.theempire.tech",
        "desaparecidosterremotovenezuela.com",
    ]

    custom_settings = {
        "PLAYWRIGHT_ENABLED": True,
        "DOWNLOAD_HANDLERS": {
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "PLAYWRIGHT_LAUNCH_OPTIONS": {
            "headless": True,
            "executable_path": (
                r"C:\Users\Darm_\AppData\Local\ms-playwright"
                r"\chromium_headless_shell-1228\chrome-headless-shell-win64"
                r"\chrome-headless-shell.exe"
            ),
        },
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 30_000,
        "DOWNLOAD_DELAY": 0.5,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 4,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    }

    def __init__(self, start_page: int | str = 1, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_page = int(start_page)
        self._token: str | None = None
        self._token_ts: float = 0.0
        # pending page requests waiting for a fresh token
        self._pending_pages: list[int] = []

    # ------------------------------------------------------------------
    # Token acquisition via Playwright
    # ------------------------------------------------------------------

    async def start(self) -> AsyncIterator:
        """Boot: load the real site with Playwright to seed the first token."""
        yield scrapy.Request(
            SITE_URL,
            callback=self._handle_token_page,
            errback=self.handle_error,
            dont_filter=True,
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "playwright_context": "default",
                "page_number": self.start_page,
            },
        )

    async def _handle_token_page(self, response: Response) -> AsyncIterator:
        """Extract a fresh reCAPTCHA token and kick off pagination."""
        page = response.meta.get("playwright_page")
        page_number: int = response.meta.get("page_number", 1)

        try:
            # Wait until reCAPTCHA is ready
            await page.wait_for_function("typeof grecaptcha !== 'undefined'", timeout=15_000)
            await page.wait_for_function(
                "typeof grecaptcha.execute === 'function'", timeout=10_000
            )
            token: str = await page.evaluate(
                f"grecaptcha.execute('{RECAPTCHA_SITE_KEY}', {{action: 'homepage'}})"
            )
            self._token = token
            self._token_ts = time.monotonic()
            logger.info("reCAPTCHA token obtained (page %d), length=%d", page_number, len(token))
        except Exception as exc:
            logger.error("Failed to obtain reCAPTCHA token: %s", exc)
        finally:
            await page.close()

        if not self._token:
            logger.error("No reCAPTCHA token — aborting crawl")
            return

        # Flush any pages that were waiting for a token refresh
        pages_to_request = self._pending_pages.copy()
        self._pending_pages.clear()
        if not pages_to_request:
            pages_to_request = [page_number]

        for pnum in pages_to_request:
            yield self._api_request(pnum)

    # ------------------------------------------------------------------
    # API pagination
    # ------------------------------------------------------------------

    def _api_headers(self) -> dict:
        return {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.7",
            "content-type": "application/json",
            "origin": "https://desaparecidosterremotovenezuela.com",
            "referer": "https://desaparecidosterremotovenezuela.com/",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36"
            ),
            "x-recaptcha-token": self._token or "",
        }

    def _token_expired(self) -> bool:
        return (time.monotonic() - self._token_ts) > TOKEN_TTL

    def _api_request(self, page_number: int) -> scrapy.Request:
        return scrapy.Request(
            _build_url(page_number),
            callback=self.parse,
            errback=self.handle_error,
            headers=self._api_headers(),
            meta={
                "handle_httpstatus_list": [400, 403, 404, 429, 500],
                "page_number": page_number,
            },
        )

    def _refresh_token_request(self, waiting_page: int) -> scrapy.Request:
        """Return a Playwright request to get a fresh token, then resume from waiting_page."""
        logger.info("Token expired — refreshing via Playwright before page %d", waiting_page)
        self._pending_pages.append(waiting_page)
        return scrapy.Request(
            SITE_URL,
            callback=self._handle_token_page,
            errback=self.handle_error,
            dont_filter=True,
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "playwright_context": "default",
                "page_number": waiting_page,
            },
        )

    def parse(self, response: Response, **kwargs) -> Generator:
        page_number: int = response.meta.get("page_number", 1)

        if response.status == 403:
            logger.warning("403 on page %d — token may have expired, refreshing", page_number)
            yield self._refresh_token_request(page_number)
            return

        if response.status != 200:
            logger.warning("Non-200 (%d) from %s", response.status, response.url)
            return

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.error("JSON decode error for %s: %s", response.url, e)
            return

        records = data.get("items", [])
        if records:
            self.crawler.stats.inc_value("records_extracted", len(records))
            yield self.make_item(response, records)

        current_page = data.get("page", page_number)
        total_pages = data.get("totalPages", 1)
        logger.info("Page %d/%d scraped (%d records)", current_page, total_pages, len(records))

        if current_page < total_pages:
            next_page = current_page + 1
            if self._token_expired():
                yield self._refresh_token_request(next_page)
            else:
                yield self._api_request(next_page)

    def parse_records(self, response: Response) -> list[dict]:
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            return []
        return data.get("items", [])

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")
