import os

BOT_NAME = "panitascraper"
SPIDER_MODULES = ["panitascraper.spiders"]
NEWSPIDER_MODULE = "panitascraper.spiders"

ROBOTSTXT_OBEY = False
CONCURRENT_REQUESTS = 8
DOWNLOAD_DELAY = 1.0
RANDOMIZE_DOWNLOAD_DELAY = True
COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False

RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

_playwright_enabled = os.environ.get("PLAYWRIGHT_ENABLED", "false").lower() == "true"

if _playwright_enabled:
    DOWNLOAD_HANDLERS = {
        "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    }
    PLAYWRIGHT_BROWSER_TYPE = "chromium"
    PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True}
    PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30_000

ITEM_PIPELINES = {
    "panitascraper.pipelines.checksum.ChecksumPipeline": 100,
    "panitascraper.pipelines.storage.StoragePipeline": 200,
    "panitascraper.pipelines.transform.TransformPipeline": 300,
}

STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "minio")
STORAGE_BUCKET = os.environ.get("STORAGE_BUCKET", "panitas-scraper")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
MINIO_SECURE = os.environ.get("MINIO_SECURE", "false").lower() == "true"
LOCAL_STORAGE_DIR = os.environ.get("LOCAL_STORAGE_DIR", "/app/raw_files")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://panitas:panitas@localhost:5433/panitasmap")

LOG_LEVEL = os.environ.get("SCRAPY_LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

FEEDS = {}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
