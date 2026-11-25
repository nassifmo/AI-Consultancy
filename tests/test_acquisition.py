"""Exercise configured API collection using local mocked responses only."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import requests

from acquisition import CollectionError, collect_json


CONFIG = {"schema_version": "1.0", "source_id": "crm", "url": "https://company.invalid/cases",
          "records_path": "records", "query": {"since": "2026-11-01"}, "credential_env": "TEST_SOURCE_TOKEN",
          "pagination": {"mode": "next_url", "next_path": "next"}, "limits": {"retries": 1}}
TOKEN = "unique-test-credential"


class Response:
    def __init__(self, value=None, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.content = json.dumps(value).encode("utf-8")
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.content

    def close(self):
        self.closed = True


class Session:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def collect(directory, session, config=None, sleeps=None):
    return collect_json(config or CONFIG, directory, session=session,
                        environ={"TEST_SOURCE_TOKEN": TOKEN}, sleep=(sleeps if sleeps is not None else []).append)


class AcquisitionTests(unittest.TestCase):
    def test_two_pages_preserve_duplicates_and_idempotently_reuse_a_bundle(self):
        pages = ({"records": [{"id": "1"}], "next": "/cases?cursor=2"},
                 {"records": [{"id": "1"}, {"id": "2"}], "next": None})
        with TemporaryDirectory() as directory:
            session = Session(*(Response(page) for page in pages))
            first = collect(directory, session)
            second = collect(directory, Session(*(Response(page) for page in pages)))
            self.assertEqual(first, second)
            source = Path(first["source_path"]) / "records.jsonl"
            self.assertEqual([json.loads(line)["id"] for line in source.read_text().splitlines()], ["1", "1", "2"])
            self.assertEqual(len(list(Path(directory).iterdir())), 1)
            self.assertEqual(first["manifest"]["source"]["records"], 3)
            self.assertTrue(session.calls[0][1]["stream"])
            self.assertFalse(session.calls[0][1]["allow_redirects"])
            self.assertIsNone(session.calls[1][1]["params"])
            self.assertNotIn(TOKEN, (Path(first["bundle_path"]) / "manifest.json").read_text())

    def test_retry_after_waits_as_requested_and_retries_the_same_page(self):
        delayed = Response({}, status=429, headers={"Retry-After": "3"})
        session = Session(delayed, Response({"records": [], "next": None}))
        with TemporaryDirectory() as directory:
            sleeps = []
            result = collect(directory, session, sleeps=sleeps)
            self.assertEqual(sleeps, [3])
            self.assertEqual(session.calls[0][0], session.calls[1][0])
            self.assertTrue(delayed.closed)
            self.assertEqual(result["manifest"]["source"]["records"], 0)

    def test_retry_after_beyond_wait_limit_stops_without_early_retry_or_publication(self):
        delayed = Response({}, status=429, headers={"Retry-After": "999"})
        session = Session(delayed)
        with TemporaryDirectory() as directory:
            sleeps = []
            with self.assertRaisesRegex(CollectionError, "Run the collection again later"):
                collect(directory, session, sleeps=sleeps)
            self.assertEqual(sleeps, [])
            self.assertEqual(len(session.calls), 1)
            self.assertTrue(delayed.closed)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_page_failure_and_missing_completion_marker_do_not_publish(self):
        for final in (Response({}, status=500), Response({"records": [{"id": 2}]})):
            with self.subTest(final=final.status_code), TemporaryDirectory() as directory:
                pages = Session(Response({"records": [{"id": 1}], "next": "/cases?page=2"}),
                                final, Response({}, status=500))
                with self.assertRaises(CollectionError):
                    collect(directory, pages)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_overflowing_page_number_rejects_the_collection_without_publishing(self):
        overflow = Response()
        overflow.content = b'{"records":[{"measurement":1e400}],"next":null}'
        with TemporaryDirectory() as directory:
            pages = Session(Response({"records": [{"id": 1}], "next": "/cases?page=2"}), overflow)
            with self.assertRaisesRegex(CollectionError, "nonfinite numeric value"):
                collect(directory, pages)
            self.assertTrue(overflow.closed)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_foreign_pagination_and_redirect_are_rejected_before_credential_forwarding(self):
        for response in (Response({"records": [], "next": "https://other.invalid/page"}),
                         Response({}, status=302, headers={"Location": "https://other.invalid/page"})):
            with self.subTest(status=response.status_code), TemporaryDirectory() as directory:
                session = Session(response)
                with self.assertRaisesRegex(CollectionError, "another origin"):
                    collect(directory, session)
                self.assertEqual(len(session.calls), 1)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_credentials_do_not_appear_in_errors_or_published_payloads(self):
        with TemporaryDirectory() as directory:
            session = Session(requests.ConnectionError(TOKEN), requests.ConnectionError(TOKEN))
            with self.assertRaises(CollectionError) as error:
                collect(directory, session)
            self.assertNotIn(TOKEN, str(error.exception))
            with self.subTest(case="echo"), self.assertRaises(CollectionError):
                collect(directory, Session(Response({"records": [{"secret": TOKEN}], "next": None})))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_explicit_offset_completion_and_record_limits(self):
        config = deepcopy(CONFIG)
        config["pagination"] = {"mode": "offset", "offset_param": "offset", "limit_param": "limit",
                                "page_size": 2, "start": 0, "stop_on": "empty"}
        with TemporaryDirectory() as directory:
            session = Session(Response({"records": [{"id": 1}]}), Response({"records": []}))
            collect(directory, session, config)
            self.assertEqual([entry[1]["params"]["offset"] for entry in session.calls], [0, 2])
        config["limits"]["max_records"] = 1
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(CollectionError, "record limit"):
                collect(directory, Session(Response({"records": [{"id": 1}, {"id": 2}]})), config)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
