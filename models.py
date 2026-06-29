"""
SQLAlchemy models for the PanitasMap scraper subsystem.

Tables:
  spider_config  – one row per spider (schedule, urls, enabled flag)
  scrape_run     – one row per spider execution
  scraped_file   – one row per unique file (keyed by SHA-256 checksum)
  run_file       – junction: which files appeared in which run
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    JSON,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SpiderConfig(Base):
    __tablename__ = "spider_config"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True, index=True)
    urls = Column(JSON, nullable=False, default=list)
    args = Column(JSON, nullable=False, default=dict)
    schedule = Column(String(100), nullable=False, default="0 */12 * * *")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    runs = relationship("ScrapeRun", back_populates="spider", cascade="all, delete-orphan")


class ScrapeRun(Base):
    __tablename__ = "scrape_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    spider_name = Column(String(255), ForeignKey("spider_config.name", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="running")
    celery_task_id = Column(String(255), nullable=True)
    log_path = Column(String(512), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    spider = relationship("SpiderConfig", back_populates="runs")
    files = relationship("RunFile", back_populates="run", cascade="all, delete-orphan")


class ScrapedFile(Base):
    __tablename__ = "scraped_file"

    checksum = Column(String(64), primary_key=True)
    url = Column(String(2048), nullable=False)
    file_type = Column(String(20), nullable=False)
    spider_name = Column(String(255), nullable=False)
    storage_path = Column(String(1024), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    runs = relationship("RunFile", back_populates="file")


class RunFile(Base):
    __tablename__ = "run_file"
    __table_args__ = (UniqueConstraint("run_id", "checksum", name="uq_run_file"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("scrape_run.id", ondelete="CASCADE"), nullable=False, index=True)
    checksum = Column(String(64), ForeignKey("scraped_file.checksum", ondelete="CASCADE"), nullable=False)
    is_new = Column(Boolean, nullable=False, default=True)

    run = relationship("ScrapeRun", back_populates="files")
    file = relationship("ScrapedFile", back_populates="runs")


def get_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


def create_all(database_url: str) -> None:
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
