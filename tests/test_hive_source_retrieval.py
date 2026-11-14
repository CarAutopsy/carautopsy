--- a/tests/test_hive_source_retrieval.py
+++ b/tests/test_hive_source_retrieval.py
@@ -296,10 +296,22 @@ class HiveSourceRetrievalTests(unittest.TestCase):
     def test_redirect_is_never_followed(self):
-        self.connection.response = FakeResponse(status=302, headers={"Location": "http://127.0.0.1/"})
-        result = self.fetch()
-        self.assertEqual(result.reason, "redirect_not_followed")
-        self.assertEqual(self.factory.call_count, 1)
+        for status in (301, 302, 307, 308):
+            with self.subTest(status=status):
+                connection = FakeConnection(
+                    FakeResponse(status=status, headers={"Location": "http://127.0.0.1/"})
+                )
+                factory = Mock(return_value=connection)
+                with patch(
+                    "scripts.hive_source_retrieval._PinnedHTTPSConnection", factory
+                ):
+                    result = fetch_source(
+                        URL,
+                        approved_hosts=HOSTS,
+                        resolver=self.resolver,
+                        clock=lambda: 0.0,
+                    )
+                self.assertEqual(result.outcome, "rejected")
+                self.assertEqual(result.reason, "redirect_not_followed")
+                self.assertEqual(factory.call_count, 1)
+                self.assertEqual(connection.request_args[0], "GET")
+                self.assertTrue(connection.closed)
+
+    def test_redirect_response_issues_exactly_one_http_request(self):
+        self.connection.response = FakeResponse(
+            status=302, headers={"Location": "https://attacker.example/target"}
+        )
+        result = self.fetch()
+        self.assertEqual(result.outcome, "rejected")
+        self.assertEqual(result.reason, "redirect_not_followed")
+        self.assertIsNotNone(self.connection.request_args)
+        self.assertEqual(self.factory.call_count, 1)
+        self.assertTrue(self.connection.closed)
