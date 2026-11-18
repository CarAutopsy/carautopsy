import json
import unittest
from scripts.deepseek_pr_audit import MAX_FINDINGS, parse_response, render

def finding():
    return {"severity":"low","path":"a.py","line":1,"title":"t","description":"d","recommendation":"r","confidence":0.5}

class DeepSeekAuditParserTests(unittest.TestCase):
    def test_valid_empty_findings(self):
        self.assertEqual(parse_response('{"summary":"ok","findings":[]}'),{"summary":"ok","findings":[]})
    def test_valid_finding(self):
        obj=parse_response('{"summary":"x","findings":[{"severity":"high","path":"a.py","line":2,"title":"bug","description":"desc","recommendation":"fix","confidence":0.9}]}')
        self.assertEqual(obj["findings"][0]["line"],2); self.assertEqual(obj["findings"][0]["confidence"],0.9)
    def test_rejects_invalid_json_and_schema(self):
        for raw in ("bad",'{"findings":[]}','{"summary":"x","findings":[{"severity":"urgent"}]}'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError): parse_response(raw)
    def test_rejects_invalid_line_confidence(self):
        for raw in ('{"summary":"x","findings":[{"severity":"high","path":"a","line":0,"title":"t","description":"d","recommendation":"r","confidence":0.5}]}',
                    '{"summary":"x","findings":[{"severity":"high","path":"a","title":"t","description":"d","recommendation":"r","confidence":2}]}',
                    '{"summary":"x","findings":[{"severity":"high","path":"a","line":true,"title":"t","description":"d","recommendation":"r","confidence":0.5}]}',
                    '{"summary":"x","findings":[{"severity":"high","path":"a","title":"t","description":"d","recommendation":"r","confidence":true}]}'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError): parse_response(raw)
    def test_count_boundary(self):
        payload={"summary":"x","findings":[finding() for _ in range(MAX_FINDINGS)]}
        self.assertEqual(len(parse_response(json.dumps(payload))["findings"]),MAX_FINDINGS)
        payload["findings"].append(finding())
        with self.assertRaises(ValueError): parse_response(json.dumps(payload))
    def test_default_confidence_render_safe(self):
        obj=parse_response('{"summary":"x","findings":[{"severity":"low","path":"a","title":"t","description":"d","recommendation":"r"}]}')
        self.assertEqual(obj["findings"][0]["confidence"],0)
        obj.update({"audit_status":"COMPLETED","base_sha":"base","head_sha":"abc","model":"m"})
        self.assertIn("0.00",render(obj))
if __name__=="__main__": unittest.main()
