import hashlib
import unittest
from unittest.mock import MagicMock, patch

from panitascraper.items import ScrapedPageItem


def _run_checksum(body: bytes, db_result=None):
    from panitascraper.pipelines.checksum import ChecksumPipeline
    pipeline = ChecksumPipeline.__new__(ChecksumPipeline)
    pipeline.engine = MagicMock()
    item = ScrapedPageItem(url="https://x.com", body=body, file_type="json", spider_name="t", run_id="r")
    spider = MagicMock()
    with patch("panitascraper.pipelines.checksum.Session") as MockSession:
        sess = MagicMock()
        sess.__enter__ = MagicMock(return_value=sess)
        sess.__exit__ = MagicMock(return_value=False)
        sess.get.return_value = db_result
        MockSession.return_value = sess
        return pipeline.process_item(item, spider)


class TestChecksumPipeline(unittest.TestCase):
    def test_checksum_computed(self):
        body = b'{"test": 1}'
        result = _run_checksum(body)
        self.assertEqual(result["checksum"], hashlib.sha256(body).hexdigest())

    def test_new_file(self):
        self.assertTrue(_run_checksum(b"fresh")["is_new"])

    def test_duplicate_file(self):
        self.assertFalse(_run_checksum(b"seen", db_result=MagicMock())["is_new"])


class TestTransformPipeline(unittest.TestCase):
    def _pipeline(self):
        from panitascraper.pipelines.transform import TransformPipeline
        p = TransformPipeline.__new__(TransformPipeline)
        return p

    def test_status_normalisation(self):
        from panitascraper.pipelines.transform import DEFAULT_STATUS_MAP
        result = self._pipeline()._normalize_status({"tipo_reporte": "Hospitalizado"}, DEFAULT_STATUS_MAP)
        self.assertEqual(result["tipo_reporte"], "ingresado")

    def test_fallecido(self):
        from panitascraper.pipelines.transform import DEFAULT_STATUS_MAP
        result = self._pipeline()._normalize_status({"tipo_reporte": "fallecido"}, DEFAULT_STATUS_MAP)
        self.assertEqual(result["tipo_reporte"], "fallecido")

    def test_unknown_defaults_to_ingresado(self):
        from panitascraper.pipelines.transform import DEFAULT_STATUS_MAP
        result = self._pipeline()._normalize_status({"tipo_reporte": "xyzzy"}, DEFAULT_STATUS_MAP)
        self.assertEqual(result["tipo_reporte"], "ingresado")

    def test_provenance(self):
        result = self._pipeline()._add_provenance({}, "https://x.com", "run-1")
        self.assertIn("https://x.com", result["notas"])
        self.assertIn("run-1", result["notas"])

    def test_field_map(self):
        result = self._pipeline()._map_fields({"full": "Ana", "id": "123"}, {"nombre": "full", "cedula": "id"})
        self.assertEqual(result["nombre"], "Ana")
        self.assertEqual(result["cedula"], "123")


class TestHospitalJsonSpider(unittest.TestCase):
    def _resp(self, body, status=200):
        from scrapy.http import TextResponse
        return TextResponse(url="https://x.com", body=body, encoding="utf-8",
                            headers={"Content-Type": b"application/json"},
                            status=status)

    def _spider(self):
        from panitascraper.spiders.hospital_json import HospitalJsonSpider
        return HospitalJsonSpider.__new__(HospitalJsonSpider)

    def test_parses_envelope(self):
        records = self._spider().parse_records(self._resp(b'{"pacientes": [{}, {}]}'))
        self.assertEqual(len(records), 2)

    def test_parses_bare_list(self):
        records = self._spider().parse_records(self._resp(b'[{}]'))
        self.assertEqual(len(records), 1)

    def test_non_200_empty(self):
        self.assertEqual(self._spider().parse_records(self._resp(b"", status=503)), [])

    def test_bad_json_empty(self):
        self.assertEqual(self._spider().parse_records(self._resp(b"not json")), [])

    def test_transform_normalises(self):
        raw = {"cedula": 42, "nombre_completo": "  Jane  Doe  ", "edad": 30}
        result = self._spider().transform_record(raw)
        self.assertEqual(result["cedula"], "42")
        self.assertEqual(result["nombre_completo"], "Jane Doe")
        self.assertEqual(result["edad"], "30")


if __name__ == "__main__":
    unittest.main()
