import unittest
from scripts.deepseek_pr_audit import parse_response

class DeepSeekAuditParserTests(unittest.TestCase):
    def test_valid_empty_findings(self):
        self.assertEqual(parse_response('{"summary":"ok","findings":[]}'),{"summary":"ok","findings":[]})

    def test_valid_finding(self):
        obj=parse_response('{"summary":"x","findings":[{"severity":"high","path":"a.py","line":2,"title":"bug","description":"desc","recommendation":"fix","confidence":0.9}]}')
        self.assertEqual(obj["findings"][0]["line"],2)

    def test_rejects_invalid_json_and_schema(self):
        for raw in ("bad", '{"findings":[]}', '{"summary":"x","findings":[{"severity":"urgent"}]}'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError): parse_response(raw)

    def test_rejects_invalid_line_confidence_and_limit(self):
        for raw in ('{"summary":"x","findings":[{"severity":"high","path":"a","line":0,"title":"t","description":"d","recommendation":"r","confidence":0.5}]}',
                    '{"summary":"x","findings":[{"severity":"high","path":"a","title":"t","description":"d","recommendation":"r","confidence":2}]}'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError): parse_response(raw)

if __name__=="__main__": unittest.main()
