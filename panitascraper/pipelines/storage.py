import io
import logging
from pathlib import Path

from itemadapter import ItemAdapter
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from models import RunFile, ScrapedFile, get_engine

logger = logging.getLogger(__name__)

_MIME_TO_EXT = {
    "application/json": "json",
    "text/html": "html",
    "application/xml": "xml",
    "text/xml": "xml",
    "application/pdf": "pdf",
    "text/csv": "csv",
    "text/plain": "txt",
}


class _MinIOBackend:
    def __init__(self, endpoint, access_key, secret_key, bucket, secure=False):
        from minio import Minio
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = bucket
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except Exception as e:
            logger.warning("Could not ensure MinIO bucket: %s", e)

    def save(self, key, data, content_type):
        self.client.put_object(self.bucket, key, io.BytesIO(data), length=len(data), content_type=content_type)
        return f"{self.bucket}/{key}"


class _S3Backend:
    def __init__(self, bucket, access_key=None, secret_key=None):
        import boto3
        kwargs = {"aws_access_key_id": access_key, "aws_secret_access_key": secret_key} if access_key else {}
        self.client = boto3.client("s3", **kwargs)
        self.bucket = bucket

    def save(self, key, data, content_type):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return f"s3://{self.bucket}/{key}"


class _LocalBackend:
    def __init__(self, base_dir, bucket):
        self.base = Path(base_dir) / bucket
        self.base.mkdir(parents=True, exist_ok=True)

    def save(self, key, data, content_type):
        dest = self.base / key
        dest.write_bytes(data)
        return str(dest)


class StoragePipeline:
    def __init__(self, settings):
        self.settings = settings
        self.backend = None
        self.engine = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(settings=crawler.settings)

    def open_spider(self, spider):
        s = self.settings
        backend = s.get("STORAGE_BACKEND", "minio")
        bucket = s.get("STORAGE_BUCKET", "panitas-scraper")
        if backend == "minio":
            self.backend = _MinIOBackend(s.get("MINIO_ENDPOINT"), s.get("MINIO_ACCESS_KEY"), s.get("MINIO_SECRET_KEY"), bucket, s.getbool("MINIO_SECURE", False))
        elif backend == "s3":
            self.backend = _S3Backend(bucket, s.get("MINIO_ACCESS_KEY"), s.get("MINIO_SECRET_KEY"))
        else:
            self.backend = _LocalBackend(s.get("LOCAL_STORAGE_DIR", "/app/raw_files"), bucket)
        self.engine = get_engine(s.get("DATABASE_URL"))

    def close_spider(self, spider):
        if self.engine:
            self.engine.dispose()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        is_new = adapter.get("is_new", True)
        checksum = adapter["checksum"]
        run_id = adapter["run_id"]

        with Session(self.engine) as session:
            if is_new:
                ext = adapter.get("file_type", "bin")
                key = f"{checksum}.{ext}"
                ext_to_mime = {v: k for k, v in _MIME_TO_EXT.items()}
                content_type = ext_to_mime.get(ext, "application/octet-stream")
                try:
                    storage_path = self.backend.save(key, adapter["body"], content_type)
                except Exception as exc:
                    logger.error("Storage error for %s: %s", checksum, exc)
                    storage_path = None
                adapter["storage_path"] = storage_path
                session.merge(ScrapedFile(
                    checksum=checksum,
                    url=adapter.get("url", ""),
                    file_type=adapter.get("file_type", "unknown"),
                    spider_name=adapter.get("spider_name", ""),
                    storage_path=storage_path,
                ))

            session.execute(
                pg_insert(RunFile.__table__)
                .values(run_id=run_id, checksum=checksum, is_new=is_new)
                .on_conflict_do_nothing(constraint="uq_run_file")
            )
            session.commit()

        return item
