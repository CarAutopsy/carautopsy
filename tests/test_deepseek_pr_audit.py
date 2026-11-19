import json
import unittest
import tempfile
from unittest.mock import patch
from scripts.deepseek_pr_audit import MAX_FINDINGS, MAX_DIFF_BYTES, parse_response, render, md_escape, bounded_diff, run, MARKER

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
        for raw in ('{"summary":"x","findings":[{"severity":"high","path":"a","line":0,"title":"t","description":"d","recommendation":"r","confidence":0.5]}',
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
    def test_provider_text_cannot_create_markdown_blocks(self):
        escaped=md_escape("safe\n# forged heading\n---\n- forged list")
        self.assertNotIn("\n",escaped)
        self.assertNotIn("<",escaped)
        self.assertIn(r"\#",escaped)
    def test_render_treats_untrusted_path_as_plain_text(self):
        payload={"summary":"ok","findings":[finding()]}
        payload.update({"audit_status":"COMPLETED","base_sha":"base","head_sha":"head","model":"m"})
        payload["findings"][0]["path"]="`\n# injected heading"
        report=render(payload)
        self.assertNotIn("\n# injected heading",report)
        self.assertIn(r"\`",report)
    def test_bounded_diff_respects_byte_cap_at_utf8_boundary(self):
        with tempfile.NamedTemporaryFile() as patch_file:
            patch_file.write((b"x"*(MAX_DIFF_BYTES-4))+"é".encode("utf-8")+b"tail")
            patch_file.flush()
            diff,truncated=bounded_diff(patch_file.name)
        self.assertTrue(truncated)
        self.assertLessEqual(len(diff.encode("utf-8")),MAX_DIFF_BYTES)
        self.assertIn(MARKER,diff)
    def test_run_rejects_non_stop_finish_reason(self):
        class FakeResponse:
            def raise_for_status(self): pass
            def json(self):
                return {"choices":[{"finish_reason":"length","message":{"content":'{"summary":"ok","findings":[]}'}}]}
        with patch("scripts.deepseek_pr_audit.requests.post",return_value=FakeResponse()):
            with self.assertRaisesRegex(ValueError,"incomplete"):
                run("diff","head","base","test-key")

if __name__=="__main__": unittest.main()
