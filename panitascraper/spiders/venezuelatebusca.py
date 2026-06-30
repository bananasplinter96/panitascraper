"""
VenezuelaTeBuscaSpider — Playwright-based spider for venezuelatebusca.com.

No REST API exists. Data is server-side rendered via React Router v7 and embedded
in window.__reactRouterContext as streamed loader data. Pagination uses a cursor
(UUID of the last record). The spider:
  1. Loads the page with Playwright.
  2. Extracts persons from window.__reactRouterDataRouter.state.loaderData.
  3. Navigates via the React Router client router with the nextCursor until hasMore=false.

Filters used: status=all, visibility=all (fetches both missing and found).

Stats visible on site (aggregated from multiple sources):
  total ~70k, missing ~47k, found ~22k — but only records submitted to THIS
  site are accessible; the count grows as new registrations arrive.

Fields per record: id, firstName, lastName, age, gender, lastSeen, status,
photoUrl, createdAt, updatedAt, lastActivityAt, reporter (name/phone/email),
sources, tips.
"""

import json
import logging
from typing import AsyncIterator, Generator

import scrapy
from scrapy.http import Response

from panitascraper.spiders.base import BaseSpider

logger = logging.getLogger(__name__)

SITE_URL = "https://venezuelatebusca.com/?status=all&visibility=all"

# JS to read persons + pagination from the React Router state
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

# JS to navigate React Router to the next cursor page
_JS_NAVIGATE = "window.__reactRouterDataRouter.navigate({0})"

# JS to read state AFTER a client-side navigation (router state, not SSR context)
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
    allowed_domains = ["venezuelatebusca.com"]

    custom_settings = {
        "DOWNLOAD_HANDLERS": {
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "PLAYWRIGHT_LAUNCH_OPTIONS": {
            # Use full Chrome (not headless shell) to avoid Cloudflare bot detection
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
        all_records: list[dict] = []

        try:
            # Remove automation signals before Cloudflare checks
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined })"
            )

            # If Cloudflare challenge page, wait for it to resolve
            if response.status in (403, 429, 503):
                logger.info("Got %d — waiting for Cloudflare challenge to resolve...", response.status)
                await page.wait_for_url("**/venezuelatebusca.com/**", timeout=20_000)
                await page.wait_for_load_state("networkidle", timeout=20_000)

            # Wait for React Router hydration
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
                    all_records.extend(persons)
                    logger.info(
                        "Page %d: %d records (total so far: %d) | hasMore=%s",
                        page_num, len(persons), len(all_records), pagination.get("hasMore"),
                    )

                if not pagination.get("hasMore") or not pagination.get("nextCursor"):
                    logger.info("Pagination complete after %d pages (%d records)", page_num, len(all_records))
                    break

                # Navigate to next cursor page via React Router client router
                cursor = pagination["nextCursor"]
                next_url = f"/?status=all&visibility=all&cursor={cursor}"
                await page.evaluate(f'window.__reactRouterDataRouter.navigate("{next_url}")')
                # Wait for new persons to load
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

        if all_records:
            self.crawler.stats.inc_value("records_extracted", len(all_records))
            yield self._make_synthetic_item(response, all_records)

    def _make_synthetic_item(self, response: Response, records: list[dict]):
        """Wrap all collected records into a single item for the pipeline."""
        from panitascraper.items import ScrapedPageItem
        import json as _json
        body = _json.dumps(records).encode("utf-8")
        return ScrapedPageItem(
            url=SITE_URL,
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
