--- a/docs/operations/HIVE_SOURCE_RETRIEVAL.md
+++ b/docs/operations/HIVE_SOURCE_RETRIEVAL.md
@@ -30,6 +30,8 @@ The following components are wired into the research-only path in `scripts/auto
 
 `scripts/hive_source_retrieval.py`: callback-free HTTPS-only DNS-pinned transport, redirect rejection, public-address checks, bounded response/time limits, and safe retrieval metadata. It is a transport primitive, not a policy authorization; production target fetches must pass through `hive_evidence.py` after the owner-controlled robots/terms precheck.
+
+Redirect responses are detected after the first successful TLS connection and are never followed. The transport issues exactly one HTTP request for an approved target URL; a 301, 302, 307, or 308 response returns `redirect_not_followed` without issuing a second request or opening another connection.
 
 - `scripts/hive_source_extract.py`: visible HTML text, strict UTF-8 plain text, and page-bounded PDF extraction. HTML and PDF parsing use OS-resource-limited workers (512 MiB address-space ceilings, 5-second CPU limit, 6.5-second parent timeout, bounded input/output, and minimal environments without provider credentials). The worker does not establish a separate network namespace; its parser path must remain free of network access.
