"""Чтение ленты: имя операции, нормализация SNIPPET, fingerprint (спека разд. 8–12)."""

from profi.integration.feed import _fingerprint, _operation_name, normalize


class TestOperationName:
    def test_from_operation_name_field(self):
        body = {"operationName": "BoSearchBoardItems", "variables": {}}
        assert _operation_name(body) == "BoSearchBoardItems"

    def test_from_query_comment(self):
        # живой факт билда 2026-08-31: operationName отсутствует, имя в тексте query
        body = {"query": "#prfrtkn: abc\n    query BoSearchBoardItems($filter: Filter)"}
        assert _operation_name(body) == "BoSearchBoardItems"

    def test_extracts_any_operation(self):
        # функция только извлекает имя; сверка с эталоном (OPERATION) — выше по стеку
        assert _operation_name({"query": "query Other($x: Int)"}) == "Other"

    def test_missing(self):
        assert _operation_name({}) is None
        assert _operation_name({"query": ""}) is None

    def test_not_a_dict(self):
        assert _operation_name(None) is None
        assert _operation_name("query X") is None


def _payload(items):
    return {
        "data": {
            "boSearchBoardItems": {
                "items": items,
                "totalCount": 42,
                "nextCursor": "abc",
                "serverTs": 123,
            }
        }
    }


class TestNormalize:
    def test_snippet_and_meta(self):
        snap = normalize(
            _payload(
                [
                    {
                        "id": "777",
                        "type": "SNIPPET",
                        "title": "ЕГЭ информатика",
                        "description": "дистанционно",
                        "price": {"value": "1500 ₽"},
                        "lastUpdateDate": "1700000000",
                        "isFresh": True,
                        "badges": [{"id": "hot"}],
                        "geo": {"remote": {"prefix": "Дистанционно", "suffix": ""}},
                    }
                ]
            )
        )
        assert snap.total_count == 42
        s = snap.snippets[0]
        assert s.id == "777" and s.price_raw == "1500 ₽"
        assert s.last_update == 1700000000 and s.is_fresh
        assert s.badges == ["hot"] and s.geo_remote == "Дистанционно"

    def test_non_snippet_items_skipped(self):
        snap = normalize(
            _payload(
                [
                    {"id": "1", "type": "SNIPPET", "title": "t", "description": "d"},
                    {"id": "2", "type": "STORIES"},
                    {"id": "3", "type": "DIVIDER"},
                ]
            )
        )
        assert [x.id for x in snap.snippets] == ["1"]

    def test_defensive_field_forms(self):
        # отсутствие/нестандартная форма полей не роняет нормализацию
        snap = normalize(
            _payload(
                [
                    {
                        "id": "9",
                        "type": "SNIPPET",
                        "price": "500 ₽",  # скаляр вместо dict
                        "geo": {"remote": "Дистанционно"},  # строка вместо dict
                        "lastUpdateDate": 1700000000.0,  # float
                        "badges": ["plain"],  # строки вместо dict
                    }
                ]
            )
        )
        s = snap.snippets[0]
        assert s.price_raw == "500 ₽"
        assert s.geo_remote == "Дистанционно"
        assert s.last_update == 1700000000
        assert s.badges == ["plain"]

    def test_fingerprint_same_content(self):
        item = {"id": "1", "type": "SNIPPET", "lastUpdateDate": 5}
        a, b = normalize(_payload([item])), normalize(_payload([dict(item)]))
        assert _fingerprint(a.raw) == _fingerprint(b.raw)

    def test_fingerprint_differs_on_update(self):
        a = normalize(_payload([{"id": "1", "type": "SNIPPET", "lastUpdateDate": 5}]))
        b = normalize(_payload([{"id": "1", "type": "SNIPPET", "lastUpdateDate": 6}]))
        assert _fingerprint(a.raw) != _fingerprint(b.raw)
