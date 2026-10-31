"""Cloudflare 522 must back off, preserve data, and never start paid AI."""
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, call, patch
from urllib.error import HTTPError

import news_pipeline as pipeline
import supabase_client as db


def http_error(status, body=None, headers=None):
    payload = json.dumps(body if body is not None else {"message": "Unavailable"}).encode()
    return HTTPError("https://database.test/rest/v1/sources", status, "Unavailable", headers or {}, io.BytesIO(payload))


def response(payload):
    context = MagicMock()
    context.__enter__.return_value = SimpleNamespace(read=lambda: json.dumps(payload).encode())
    return context


class SupabaseAvailabilityTests(unittest.TestCase):
    def client(self):
        with patch.dict(os.environ, {"SUPABASE_REQUEST_RETRIES": "3"}):
            return db.SupabaseRestClient("https://database.test", "DO_NOT_LOG_SECRET")

    def test_522_retries_after_the_gateway_requested_delay_and_recovers(self):
        failures = [http_error(522, {"retryable": True, "retry_after": 120}), response([{"source_id": "pap"}])]
        with patch.object(db.urllib.request, "urlopen", side_effect=failures) as request, \
             patch.object(db.time, "sleep") as sleep, patch.object(db, "log") as log:
            rows = self.client().select_all("sources")
        self.assertEqual(rows, [{"source_id": "pap"}])
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(120)
        self.assertIn("HTTP 522", log.call_args.args[1])
        self.assertIn("120 s", log.call_args.args[1])
        self.assertNotIn("DO_NOT_LOG_SECRET", str(log.call_args_list))

    def test_522_stops_after_three_attempts_and_keeps_the_failure_explicit(self):
        with patch.object(db.urllib.request, "urlopen", side_effect=[http_error(522, {"retry_after": 120}) for _ in range(3)]) as request, \
             patch.object(db.time, "sleep") as sleep, patch.object(db, "log"):
            with self.assertRaises(db.SupabaseError) as failed:
                self.client().select_all("sources")
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(120), call(120)])
        self.assertEqual(failed.exception.http_status, 522)
        self.assertTrue(failed.exception.retryable)
        self.assertEqual(failed.exception.attempts, 3)
        self.assertEqual(failed.exception.retry_after, 120)

    def test_other_cloudflare_origin_errors_use_a_bounded_retry_count(self):
        for status in (520, 521, 523, 524):
            with self.subTest(status=status), patch.object(db.urllib.request, "urlopen", side_effect=[http_error(status), response([])]), \
                 patch.object(db.time, "sleep") as sleep, patch.object(db, "log"):
                self.assertEqual(self.client().select_all("sources"), [])
                sleep.assert_called_once_with(120)

    def test_retry_after_header_and_json_both_apply(self):
        with patch.object(db.urllib.request, "urlopen", side_effect=[http_error(503, {"retry_after": 45}, {"Retry-After": "30"}), response([])]), \
             patch.object(db.time, "sleep") as sleep, patch.object(db, "log"):
            self.client().select_all("sources")
        sleep.assert_called_once_with(45)

    def test_retry_after_http_date_is_honored(self):
        header = {"Retry-After": "Thu, 01 Jan 1970 00:33:20 GMT"}
        with patch.object(db.time, "time", return_value=1880):
            self.assertEqual(db._retry_delay_seconds(503, header, "{}", 0), 120)

    def test_invalid_retry_hints_use_normal_backoff(self):
        for body, header in (("<html>Bad gateway</html>", "invalid"), ('{"retry_after":"NaN"}', "-1"), ('[]', "Infinity")):
            with self.subTest(body=body):
                self.assertEqual(db._retry_delay_seconds(503, {"Retry-After": header}, body, 0), 1)

    def test_very_long_retry_after_stops_instead_of_retrying_too_early(self):
        with patch.object(db.urllib.request, "urlopen", side_effect=http_error(503, {"retry_after": 3600})) as request, \
             patch.object(db.time, "sleep") as sleep:
            with self.assertRaises(db.SupabaseError) as failed:
                self.client().select_all("sources")
        request.assert_called_once()
        sleep.assert_not_called()
        self.assertEqual(failed.exception.retry_after, 3600)

    def test_auth_and_permanent_http_errors_fail_without_retries(self):
        for status in (400, 401, 403, 404):
            with self.subTest(status=status), patch.object(db.urllib.request, "urlopen", side_effect=http_error(status)) as request, \
                 patch.object(db.time, "sleep") as sleep:
                with self.assertRaises(db.SupabaseError) as failed:
                    self.client().select_all("sources")
                request.assert_called_once()
                sleep.assert_not_called()
                self.assertFalse(failed.exception.retryable)
                self.assertEqual(failed.exception.http_status, status)

    def test_transport_timeouts_keep_existing_bounded_retries(self):
        with patch.object(db.urllib.request, "urlopen", side_effect=TimeoutError("read timeout")) as request, \
             patch.object(db.time, "sleep") as sleep:
            with self.assertRaises(db.SupabaseError) as failed:
                self.client().select_all("sources")
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(1), call(2)])
        self.assertEqual(failed.exception.attempts, 3)
        self.assertTrue(failed.exception.retryable)

    def test_failed_initial_pull_stops_before_harvesting_ai_writes_and_export(self):
        for status in (401, 522):
            with self.subTest(status=status), TemporaryDirectory() as folder:
                output = Path(folder) / "output"
                error = db.SupabaseError("Supabase GET sources HTTP " + str(status), http_status=status, retryable=status == 522)
                with patch("sys.argv", ["news_pipeline.py", "--ai-only", "--db", str(Path(folder) / "db")]), \
                     patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}), \
                     patch.object(pipeline, "SupabaseRestClient"), \
                     patch.object(pipeline, "pull_state", side_effect=error), \
                     patch.object(pipeline.subprocess, "run") as harvest, \
                     patch.object(pipeline, "push_run") as push, \
                     patch.object(pipeline, "analyze_run") as ai, \
                     patch.object(pipeline, "latest_run_id") as run, patch.object(pipeline, "log") as log:
                    self.assertEqual(pipeline.main(), 1)
                harvest.assert_not_called()
                push.assert_not_called()
                ai.assert_not_called()
                run.assert_not_called()
                self.assertEqual(output.read_text(), "skip_public_export=true\n")
                self.assertTrue(any("AI nie zostały uruchomione" in str(c) for c in log.call_args_list))


if __name__ == "__main__":
    unittest.main()
