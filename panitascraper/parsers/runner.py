"""
Parser runner — reads raw files from MinIO, parses them, and logs results.

Usage:
    uv run python -m panitascraper.parsers.runner [--spider NAME] [--dry-run]

Logs are written to ./logs/parsers/ (bind-mounted outside Docker).
"""

import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

from . import PARSERS

LOG_DIR = os.environ.get("PARSER_LOG_DIR", os.path.join(os.getcwd(), "logs", "parsers"))


def setup_logging() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"parser_run_{timestamp}.log")

    logger = logging.getLogger("parsers")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info("Log file: %s", log_file)
    return logger


def run(spider_filter: str | None = None, dry_run: bool = False):
    logger = setup_logging()
    from minio import Minio
    import psycopg2

    db_url = os.environ.get("DATABASE_URL", "")
    minio_endpoint = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
    minio_access = os.environ.get("MINIO_ACCESS_KEY", "")
    minio_secret = os.environ.get("MINIO_SECRET_KEY", "")
    minio_secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"
    bucket = os.environ.get("STORAGE_BUCKET", "panitas-scraper")

    client = Minio(minio_endpoint, access_key=minio_access, secret_key=minio_secret, secure=minio_secure)
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    cur.execute(
        "SELECT spider_name, checksum, file_type, url FROM scraped_file ORDER BY spider_name, first_seen_at"
    )
    rows = cur.fetchall()

    spider_files = defaultdict(list)
    for spider_name, checksum, file_type, url in rows:
        spider_files[spider_name].append((checksum, file_type, url))

    spiders_to_run = [spider_filter] if spider_filter else sorted(spider_files.keys())

    stats = {}
    total_parsed = 0
    total_errors = 0
    total_files = 0
    start_time = time.time()

    logger.info("=" * 60)
    logger.info("Parser run started")
    logger.info("Spiders: %s", ", ".join(spiders_to_run))
    logger.info("Dry run: %s", dry_run)
    logger.info("=" * 60)

    for spider in spiders_to_run:
        if spider not in PARSERS:
            logger.warning("No parser for spider '%s', skipping", spider)
            continue

        parse_fn = PARSERS[spider]
        files = spider_files.get(spider, [])
        spider_parsed = 0
        spider_errors = 0
        spider_empty = 0
        spider_start = time.time()

        logger.info("--- %s: %d files ---", spider, len(files))

        for checksum, file_type, url in files:
            fname = f"{checksum}.{file_type}"
            total_files += 1
            try:
                obj = client.get_object(bucket, fname)
                raw = obj.read()
                obj.close()

                records = parse_fn(raw, url)
                count = len(records)
                spider_parsed += count

                if count == 0:
                    spider_empty += 1
                    logger.debug("%s: %s → 0 records (url: %s)", spider, checksum[:16], url[:80])
                else:
                    logger.debug("%s: %s → %d records", spider, checksum[:16], count)

            except Exception as e:
                spider_errors += 1
                logger.error("%s: %s FAILED — %s: %s (url: %s)",
                             spider, checksum[:16], type(e).__name__, e, url[:80])

        elapsed = time.time() - spider_start
        total_parsed += spider_parsed
        total_errors += spider_errors

        stats[spider] = {
            "files": len(files),
            "parsed": spider_parsed,
            "errors": spider_errors,
            "empty_files": spider_empty,
            "elapsed_s": round(elapsed, 1),
        }

        logger.info(
            "%s: %d files → %d records parsed, %d errors, %d empty files (%.1fs)",
            spider, len(files), spider_parsed, spider_errors, spider_empty, elapsed
        )

    total_elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info("%-25s %6s %8s %6s %6s %7s", "Spider", "Files", "Parsed", "Errors", "Empty", "Time")
    logger.info("-" * 60)
    for spider, s in sorted(stats.items()):
        logger.info("%-25s %6d %8d %6d %6d %6.1fs",
                     spider, s["files"], s["parsed"], s["errors"], s["empty_files"], s["elapsed_s"])
    logger.info("-" * 60)
    logger.info("%-25s %6d %8d %6d %13.1fs", "TOTAL", total_files, total_parsed, total_errors, total_elapsed)
    logger.info("=" * 60)

    stats_file = os.path.join(LOG_DIR, f"parser_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(stats_file, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dry_run": dry_run,
            "total_files": total_files,
            "total_parsed": total_parsed,
            "total_errors": total_errors,
            "elapsed_s": round(total_elapsed, 1),
            "spiders": stats,
        }, f, indent=2)
    logger.info("Stats written to %s", stats_file)

    conn.close()
    return total_errors == 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run parsers on scraped MinIO data")
    parser.add_argument("--spider", help="Run only this spider's parser")
    parser.add_argument("--dry-run", action="store_true", help="Parse but don't write to DB")
    args = parser.parse_args()
    ok = run(spider_filter=args.spider, dry_run=args.dry_run)
    sys.exit(0 if ok else 1)
