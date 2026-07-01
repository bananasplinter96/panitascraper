"""Tests for the EncuentralosSpider."""

import json

from scrapy.http import TextResponse, Request

from panitascraper.spiders.encuentralos import EncuentralosSpider, PAGE_SIZE


def _fake_response(url, body, status=200):
    """Build a fake Scrapy TextResponse for testing."""
    request = Request(url=url)
    return TextResponse(
        url=url, request=request, body=body.encode("utf-8"),
        encoding="utf-8", status=status,
    )


def _make_api_body(items, total):
    return json.dumps({"items": items, "total": total})


SAMPLE_RECORD = {
    "id": "a5d7d924-d6a3-424e-9074-c21c22073f4f",
    "nombre": "Betzabeth Ortiz",
    "edad": 57,
    "sexo": "Femenino",
    "descripcion": "Cédula: 6318564 · Fuente: venezuelatebusca.com",
    "foto": None,
    "ultima_ubicacion": "Ortiz",
    "ultima_lat": None,
    "ultima_lng": None,
    "ultima_vez": None,
    "reporta_contacto": None,
    "estado": "desaparecido",
    "creado": "2026-06-29T17:49:48.123Z",
    "cedula": None,
    "pv_por": None,
    "pv_contacto": None,
    "pv_lugar": None,
    "pv_salud": None,
    "pv_relacion": None,
}


class TestEncuentralosSpider:
    """Tests for EncuentralosSpider parsing and pagination."""

    def setup_method(self):
        self.spider = EncuentralosSpider()

    def test_parse_records_extracts_items(self):
        """Verifies parse_records returns the items list from API JSON."""
        body = _make_api_body([SAMPLE_RECORD], total=1)
        response = _fake_response(
            "https://encuentralos.tecnosoft.dev/api/personas?limit=100&offset=0",
            body,
        )
        records = self.spider.parse_records(response)
        assert len(records) == 1
        assert records[0]["nombre"] == "Betzabeth Ortiz"
        assert records[0]["estado"] == "desaparecido"

    def test_parse_records_handles_invalid_json(self):
        """Verifies parse_records returns empty list on malformed JSON."""
        response = _fake_response(
            "https://encuentralos.tecnosoft.dev/api/personas?limit=100&offset=0",
            "not json",
        )
        records = self.spider.parse_records(response)
        assert records == []

    def test_parse_records_handles_missing_items_key(self):
        """Verifies parse_records returns empty list if 'items' key is absent."""
        response = _fake_response(
            "https://encuentralos.tecnosoft.dev/api/personas?limit=100&offset=0",
            json.dumps({"total": 0}),
        )
        records = self.spider.parse_records(response)
        assert records == []

    def test_extract_offset(self):
        """Verifies _extract_offset parses offset from query string."""
        assert EncuentralosSpider._extract_offset(
            "https://encuentralos.tecnosoft.dev/api/personas?limit=100&offset=200"
        ) == 200

    def test_extract_offset_missing(self):
        """Verifies _extract_offset defaults to 0 when offset param is absent."""
        assert EncuentralosSpider._extract_offset(
            "https://encuentralos.tecnosoft.dev/api/personas?limit=100"
        ) == 0

    def test_start_yields_first_page(self):
        """Verifies start() generates a request for offset=0."""
        import asyncio
        async def collect():
            return [r async for r in self.spider.start()]
        requests = asyncio.run(collect())
        assert len(requests) == 1
        assert "offset=0" in requests[0].url
        assert f"limit={PAGE_SIZE}" in requests[0].url

    def test_page_size_is_100(self):
        """Verifies the page size constant is set to 100."""
        assert PAGE_SIZE == 100
