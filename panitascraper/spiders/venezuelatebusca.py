"""
VenezuelaTeBuscaSpider — Playwright-based spider for venezuelatebusca.com.
Optimizado para guardar resultados página por página en tiempo real.
"""

import json
import logging
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response
from panitascraper.items import ScrapedPageItem
from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

SITE_URL = "https://venezuelatebusca.com/?status=all&visibility=all"

_JS_READ_STATE = """
(function() {
  const router = window.__reactRouterDataRouter;
  const ctx = window.__reactRouterContext;
  const src = router?.state?.loaderData || ctx?.state?.loaderData;
  const d = src?.['routes/_index'];
  if (!d) return null;
  return JSON.stringify({
    persons: d.persons || [],
    pagination: d.pagination || { hasMore: false, nextCursor: null },
    stats: d.stats || {},
    totalCount: d.totalCount || 0,
  });
})()
"""

_JS_READ_ROUTER_STATE = """
(function() {
  const d = window.__reactRouterDataRouter?.state?.loaderData?.['routes/_index'];
  if (!d) return null;
  return JSON.stringify({
    persons: d.persons || [],
    pagination: d.pagination || { hasMore: false, nextCursor: null },
  });
})()
"""


class VenezuelaTeBuscaSpider(BaseSpider):
    name = "venezuelatebusca"
    field_map = {
        "nombre":       "full_name",
        "cedula":       "cedula",
        "edad":         "age",
        "hospital":     "location",
        "ciudad":       None,
        "tipo_reporte": "status",
        "condicion":    None,
        "estado":       "status",
        "notas":        "notes",
    }

    allowed_domains = ["venezuelatebusca.com"]

    custom_settings = {
        "DOWNLOAD_HANDLERS": {
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "PLAYWRIGHT_LAUNCH_OPTIONS": {
            "headless": False,
            "executable_path": (
                r"C:\Users\Darm_\AppData\Local\ms-playwright"
                r"\chromium-1228\chrome-win64\chrome.exe"
            ),
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        },
        "PLAYWRIGHT_CONTEXTS": {
            "default": {
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/149.0.0.0 Safari/537.36"
                ),
                "ignore_https_errors": True,
            }
        },
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 30_000,
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS": 1,
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    }

    async def start(self) -> AsyncIterator:
        yield scrapy.Request(
            SITE_URL,
            callback=self._parse_page,
            errback=self.handle_error,
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "playwright_context": "default",
                "handle_httpstatus_all": True,
            },
        )

    async def _parse_page(self, response: Response) -> AsyncIterator:
        page = response.meta["playwright_page"]
        total_scraped = 0

        try:
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined })"
            )

            if response.status in (403, 429, 503):
                logger.info("Got %d — waiting for Cloudflare challenge to resolve...", response.status)
                await page.wait_for_url("**/venezuelatebusca.com/**", timeout=20_000)
                await page.wait_for_load_state("networkidle", timeout=20_000)

            await page.wait_for_function(
                "window.__reactRouterContext?.state?.loaderData?.['routes/_index']?.persons !== undefined"
                " || window.__reactRouterDataRouter?.state?.loaderData?.['routes/_index']?.persons !== undefined",
                timeout=15_000,
            )

            page_num = 0
            while True:
                page_num += 1
                raw = await page.evaluate(_JS_READ_STATE if page_num == 1 else _JS_READ_ROUTER_STATE)
                if not raw:
                    logger.error("No loader state found on page %d", page_num)
                    break

                data = json.loads(raw)
                persons = data.get("persons", [])
                pagination = data.get("pagination", {})

                if persons:
                    total_scraped += len(persons)
                    self.crawler.stats.inc_value("records_extracted", len(persons))
                    
                    # Guardamos la página en tiempo real
                    virtual_url = f"https://venezuelatebusca.com/?status=all&visibility=all&page={page_num}"
                    yield self._make_synthetic_item(response, virtual_url, persons)

                    logger.info(
                        "Page %d: %d records (total so far: %d) | hasMore=%s",
                        page_num, len(persons), total_scraped, pagination.get("hasMore"),
                    )

                if not pagination.get("hasMore") or not pagination.get("nextCursor"):
                    logger.info("Pagination complete after %d pages (%d records)", page_num, total_scraped)
                    break

                # Navegar al siguiente cursor de página
                cursor = pagination["nextCursor"]
                next_url = f"/?status=all&visibility=all&cursor={cursor}"
                await page.evaluate(f'window.__reactRouterDataRouter.navigate("{next_url}")')
                
                await page.wait_for_function(
                    f"""
                    (function() {{
                        const d = window.__reactRouterDataRouter?.state?.loaderData?.['routes/_index'];
                        const persons = d?.persons || [];
                        return persons.length > 0 && persons[0]?.id !== '{persons[0]["id"] if persons else ""}';
                    }})()
                    """,
                    timeout=15_000,
                )

        except Exception as exc:
            logger.error("Error during page extraction: %s", exc)
        finally:
            await page.close()

    def _make_synthetic_item(self, response: Response, url: str, records: list[dict]):
        """Crea el item para ser procesado progresivamente por las pipelines."""
        body = json.dumps(records).encode("utf-8")
        return ScrapedPageItem(
            url=url,
            body=body,
            file_type="json",
            spider_name=self.name,
            run_id=self.run_id,
            records=records,
        )

    def parse_records(self, response: Response) -> list[dict]:
        return []

    def handle_error(self, failure):
        logger.error("Request failed: %s", failure.value)
        self.crawler.stats.inc_value("request_errors")