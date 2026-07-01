"""
Celery tasks + Beat scheduler for PanitasScraper.

  celery -A tasks worker --loglevel=info --concurrency=1
  celery -A tasks beat --loglevel=info
"""

import logging
import os
import uuid
from datetime import datetime, timezone

from celery import Celery
from celery.beat import Scheduler, ScheduleEntry
from celery.schedules import crontab
from crochet import setup as crochet_setup
from scrapy.crawler import CrawlerRunner
from scrapy.utils.project import get_project_settings
from sqlalchemy.orm import Session

from models import ScrapeRun, SpiderConfig, get_engine

app = Celery("panitascraper")
app.config_from_object("celeryconfig")

logger = logging.getLogger(__name__)
crochet_setup()

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_SCRAPER_LOG_DIR = os.environ.get("SCRAPER_LOG_DIR", "/app/logs")


def _get_engine():
    return get_engine(_DATABASE_URL)


@app.task(bind=True, max_retries=0, name="panitascraper.run_spider")
def run_spider(self, spider_name: str) -> dict:
    engine = _get_engine()
    run_id = str(uuid.uuid4())
    log_path = os.path.join(_SCRAPER_LOG_DIR, f"{run_id}.log")
    os.makedirs(_SCRAPER_LOG_DIR, exist_ok=True)

    with Session(engine) as session:
        run = ScrapeRun(
            id=run_id,
            spider_name=spider_name,
            status="running",
            celery_task_id=self.request.id,
            log_path=log_path,
            started_at=datetime.now(timezone.utc),
        )
        session.add(run)
        session.commit()

    logger.info("Starting spider=%s run_id=%s", spider_name, run_id)

    settings = get_project_settings()
    settings.set("LOG_FILE", log_path)
    runner = CrawlerRunner(settings)

    try:
        spider_cls = runner.spider_loader.load(spider_name)
    except KeyError:
        _fail_run(engine, run_id, "Spider not found")
        return {"status": "failed", "error": f"Spider '{spider_name}' not found"}

    @crochet_setup
    def _run():
        return runner.crawl(spider_cls, run_id=run_id)

    try:
        _run().wait(timeout=3600)
    except Exception as exc:
        logger.exception("Spider %s crashed: %s", spider_name, exc)
        _fail_run(engine, run_id, str(exc))
        return {"status": "failed", "error": str(exc)}

    with Session(engine) as session:
        run = session.get(ScrapeRun, run_id)
        summary = {
            "run_id": run_id,
            "spider": spider_name,
            "status": run.status if run else "unknown",
            "started_at": run.started_at.isoformat() if run else None,
            "finished_at": run.finished_at.isoformat() if run and run.finished_at else None,
        }

    _check_volume_alert(engine, spider_name, run_id)
    return summary


def _fail_run(engine, run_id: str, reason: str) -> None:
    with Session(engine) as session:
        run = session.get(ScrapeRun, run_id)
        if run:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            session.commit()
    logger.error("Run %s failed: %s", run_id, reason)


def _check_volume_alert(engine, spider_name: str, current_run_id: str) -> None:
    from sqlalchemy import text

    with Session(engine) as session:
        current_count = session.execute(
            text("SELECT COUNT(*) FROM run_file WHERE run_id = :rid"),
            {"rid": current_run_id},
        ).scalar() or 0

        prev = session.execute(
            text("""
                SELECT rf.run_id, COUNT(*) AS cnt
                FROM run_file rf
                JOIN scrape_run sr ON sr.id = rf.run_id
                WHERE sr.spider_name = :name
                  AND sr.status = 'success'
                  AND sr.id != :rid
                GROUP BY rf.run_id
                ORDER BY sr.started_at DESC
                LIMIT 1
            """),
            {"name": spider_name, "rid": current_run_id},
        ).fetchone()

        if prev and prev.cnt > 0:
            ratio = current_count / prev.cnt
            if ratio < 0.5:
                logger.warning(
                    "ALERT: Spider '%s' scraped %d files (%.0f%% of previous %d).",
                    spider_name, current_count, ratio * 100, prev.cnt,
                )


class DatabaseScheduler(Scheduler):
    """Beat scheduler backed by the spider_config table. Refreshes every 60 s."""

    max_interval = 60

    def __init__(self, *args, **kwargs):
        self._engine = _get_engine()
        super().__init__(*args, **kwargs)

    def setup_schedule(self):
        self._load_from_db()

    def _load_from_db(self):
        with Session(self._engine) as session:
            configs = session.query(SpiderConfig).filter_by(enabled=True).all()

        new_schedule: dict[str, ScheduleEntry] = {}
        for cfg in configs:
            parts = cfg.schedule.split()
            if len(parts) != 5:
                logger.warning("Invalid cron '%s' for spider '%s'", cfg.schedule, cfg.name)
                continue
            minute, hour, dom, moy, dow = parts
            entry = ScheduleEntry(
                name=f"spider:{cfg.name}",
                task="panitascraper.run_spider",
                schedule=crontab(minute=minute, hour=hour, day_of_month=dom, month_of_year=moy, day_of_week=dow),
                args=(cfg.name,),
                app=self.app,
            )
            new_schedule[f"spider:{cfg.name}"] = entry

        self.data = new_schedule
        logger.info("Loaded %d spider schedule(s) from DB", len(new_schedule))

    def tick(self, *args, **kwargs):
        self._load_from_db()
        return super().tick(*args, **kwargs)
