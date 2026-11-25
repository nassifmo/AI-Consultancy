"""Read configured JSON pages and publish a complete, reproducible local extract."""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
from math import isfinite
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from urllib.parse import parse_qsl, urljoin, urlsplit

import requests


class CollectionError(ValueError):
    """A collection failed without publishing a successful extract."""


DEFAULT_LIMITS = {"max_pages": 100, "max_records": 250_000, "max_bytes": 100 * 1024**2,
                  "retries": 3, "timeout_seconds": 30, "max_retry_after_seconds": 15}
SECRET_NAMES = {"authorization", "access_token", "api_key", "apikey", "password", "secret", "token"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CollectionError("The source JSON contains duplicate field names.")
        result[key] = value
    return result


def _parse_json(content):
    def reject(_):
        raise CollectionError("The source JSON contains a nonfinite numeric value.")

    def finite_float(value):
        number = float(value)
        if not isfinite(number):
            reject(value)
        return number

    try:
        return json.loads(content, object_pairs_hook=_unique_object, parse_constant=reject,
                          parse_float=finite_float)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CollectionError("The source did not return valid UTF-8 JSON.") from None


def _url(value, origin=None):
    try:
        parsed = urlsplit(value)
        current = (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except (TypeError, ValueError):
        raise CollectionError("The source URL is invalid.") from None
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment):
        raise CollectionError("Configure an HTTP(S) URL without credentials or fragments.")
    if any(key.casefold() in SECRET_NAMES for key, _ in parse_qsl(parsed.query)):
        raise CollectionError("Keep access credentials in the named environment variable.")
    if origin is not None and current != origin:
        raise CollectionError("The source attempted to paginate or redirect to another origin.")
    return current


def validate_config(config):
    """Validate the extraction settings without making a request."""
    if not isinstance(config, dict) or set(config) - {
        "schema_version", "source_id", "url", "records_path", "query", "credential_env", "pagination", "limits",
    }:
        raise CollectionError("Supply only the supported collection settings.")
    if config.get("schema_version") != "1.0":
        raise CollectionError("The collection schema_version must be 1.0.")
    if not isinstance(config.get("source_id"), str) or not config["source_id"].strip():
        raise CollectionError("Supply a source_id.")
    _url(config.get("url"))
    if not isinstance(config.get("records_path"), str):
        raise CollectionError("Specify records_path, using an empty string for a top-level list.")
    query = config.get("query", {})
    if not isinstance(query, dict) or any(not isinstance(key, str) or key.casefold() in SECRET_NAMES for key in query):
        raise CollectionError("Query parameters must be an object without credentials.")
    if any(not isinstance(key, str) or type(value) not in (str, int, float, bool, type(None)) for key, value in query.items()):
        raise CollectionError("Query parameters must have text names and scalar values.")
    credential = config.get("credential_env")
    if credential is not None and (not isinstance(credential, str) or not credential.strip()):
        raise CollectionError("credential_env must name an environment variable.")
    pagination = config.get("pagination", {})
    if not isinstance(pagination, dict) or pagination.get("mode") not in {"none", "next_url", "offset"}:
        raise CollectionError("Specify pagination mode none, next_url, or offset.")
    mode = pagination["mode"]
    if mode == "next_url" and (set(pagination) != {"mode", "next_path"}
                               or not isinstance(pagination["next_path"], str) or not pagination["next_path"]):
        raise CollectionError("next_url pagination needs a next_path supplied on every page.")
    if mode == "none" and set(pagination) != {"mode"}:
        raise CollectionError("Single-page pagination accepts only mode.")
    if mode == "offset":
        if (set(pagination) != {"mode", "offset_param", "limit_param", "page_size", "start", "stop_on"}
                or pagination.get("stop_on") not in {"empty", "short_page"}
                or type(pagination.get("page_size")) is not int or not 1 <= pagination["page_size"] <= 100_000
                or type(pagination.get("start")) is not int or pagination["start"] < 0):
            raise CollectionError("Offset pagination needs page_size, start, parameters and an explicit stop_on rule.")
        parameters = (pagination["offset_param"], pagination["limit_param"])
        if (any(not isinstance(value, str) or not value for value in parameters)
                or parameters[0] == parameters[1] or any(value.casefold() in SECRET_NAMES for value in parameters)
                or any(value in query for value in parameters)):
            raise CollectionError("Pagination parameter names must be distinct and separate from query parameters.")
    limits = {**DEFAULT_LIMITS, **config.get("limits", {})} if isinstance(config.get("limits", {}), dict) else {}
    if set(limits) != DEFAULT_LIMITS.keys():
        raise CollectionError("Supply supported collection limits.")
    for name, maximum in (("max_pages", 10_000), ("max_records", 1_000_000), ("max_bytes", 1024**3),
                          ("retries", 5), ("timeout_seconds", 120), ("max_retry_after_seconds", 60)):
        value = limits[name]
        if type(value) is not int or not (0 if name == "retries" else 1) <= value <= maximum:
            raise CollectionError(f"Invalid collection limit {name}.")
    try:
        _json(config)
    except (TypeError, ValueError):
        raise CollectionError("Collection settings must be finite JSON values.") from None
    return {**config, "query": dict(query), "limits": limits}


def _path(value, dotted):
    if dotted == "":
        return value
    for component in dotted.split("."):
        if not isinstance(value, dict) or component not in value:
            raise CollectionError("A configured records or pagination field is absent from the source response.")
        value = value[component]
    return value


def _retry_delay(header, attempt, cap):
    delay = min(2**attempt, cap)
    if header:
        try:
            requested = float(header)
        except (TypeError, ValueError):
            try:
                requested = (parsedate_to_datetime(header) - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                requested = 0
        if isfinite(requested):
            if requested > cap:
                raise CollectionError(
                    "The service requires a longer Retry-After wait than this collection allows. Run the collection again later.")
            delay = max(delay, requested, 0)
    return delay


def _page(session, url, query, token, limits, sleep, origin, remaining_bytes):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    redirects = 0
    attempt = 0
    while True:
        _url(url, origin)
        try:
            response = session.get(url, params=query, headers=headers, timeout=limits["timeout_seconds"],
                                   allow_redirects=False, stream=True)
        except requests.RequestException:
            if attempt >= limits["retries"]:
                raise CollectionError("The configured service could not be read after the allowed attempts.") from None
            sleep(_retry_delay(None, attempt, limits["max_retry_after_seconds"]))
            attempt += 1
            continue
        try:
            status = response.status_code
            if 300 <= status < 400:
                location = response.headers.get("Location")
                if not location or redirects >= 3:
                    raise CollectionError("The configured service did not provide a usable final endpoint.")
                url = urljoin(url, location)
                _url(url, origin)
                query = None
                redirects += 1
                continue
            if status == 429 or 500 <= status <= 599:
                if attempt >= limits["retries"]:
                    raise CollectionError(f"The configured service returned HTTP {status} after the allowed attempts.")
                sleep(_retry_delay(response.headers.get("Retry-After"), attempt,
                                   limits["max_retry_after_seconds"]))
                attempt += 1
                continue
            if not 200 <= status < 300:
                raise CollectionError(f"The configured service returned HTTP {status}.")
            content = bytearray()
            try:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        content.extend(chunk)
                        if len(content) > remaining_bytes:
                            raise CollectionError("The collection exceeded its configured byte limit.")
            except requests.RequestException:
                raise CollectionError("The source page ended before its content was fully received.") from None
            if token and token.encode("utf-8") in content:
                raise CollectionError("The source returned the access credential in its payload. The extract was not published.")
            return _parse_json(content.decode("utf-8-sig")), bytes(content), url
        except UnicodeError:
            raise CollectionError("The source did not return valid UTF-8 JSON.") from None
        finally:
            response.close()


def _publish(output_dir, config, content, pages):
    source_name = "records.jsonl"
    source_digest = sha256(content).hexdigest()
    stable = {"schema_version": "1.0", "source_id": config["source_id"], "config": config,
              "collector_sha256": sha256(Path(__file__).read_bytes()).hexdigest(), "pages": pages,
              "source": {"path": f"source/{source_name}", "sha256": source_digest,
                         "bytes": len(content), "records": sum(page["records"] for page in pages)},
              "pagination_status": "completed", "coverage": "requires_source_owner_confirmation"}
    collection_id = "collection-" + sha256(_json(stable)).hexdigest()[:24]
    parent = Path(output_dir)
    if parent.is_symlink():
        raise CollectionError("Choose a regular output directory.")
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / collection_id

    def existing():
        if destination.is_symlink() or not destination.is_dir():
            raise CollectionError("The collection destination is occupied.")
        source = destination / "source" / source_name
        manifest_path = destination / "manifest.json"
        if source.parent.is_symlink() or source.is_symlink() or manifest_path.is_symlink():
            raise CollectionError("The existing collection does not match its recorded files.")
        try:
            manifest = _parse_json(manifest_path.read_text(encoding="utf-8"))
            actual = {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()}
            stable_keys = {key: manifest[key] for key in stable}
            if actual != {"source/records.jsonl", "manifest.json"} or stable_keys != stable or source.read_bytes() != content:
                raise CollectionError("The existing collection does not match its recorded files.")
        except (OSError, KeyError):
            raise CollectionError("The existing collection does not match its recorded files.") from None
        return manifest

    if destination.exists() or destination.is_symlink():
        manifest = existing()
    else:
        manifest = {**stable, "collection_id": collection_id, "first_collected_at": datetime.now(UTC).isoformat()}
        with TemporaryDirectory(dir=parent, prefix=".collecting-") as temporary:
            stage = Path(temporary) / "complete"
            (stage / "source").mkdir(parents=True)
            (stage / "source" / source_name).write_bytes(content)
            (stage / "manifest.json").write_bytes(_json(manifest) + b"\n")
            try:
                stage.rename(destination)
            except OSError:
                if not destination.exists():
                    raise
                manifest = existing()
    return {"collection_id": collection_id, "bundle_path": str(destination.resolve()),
            "source_path": str((destination / "source").resolve()), "manifest": manifest}


def collect_json(config, output_dir, *, session=None, sleep=time.sleep, environ=None):
    """Collect configured pages using GET, then atomically publish the extract.

    Pagination completion only establishes that the configured extraction ended.
    Permissions, historic coverage and upstream completeness need source review.
    Repeated records remain present for the mapping and evaluator stages.
    """
    config = validate_config(config)
    environment = os.environ if environ is None else environ
    token = environment.get(config.get("credential_env")) if config.get("credential_env") else None
    if config.get("credential_env") and (not isinstance(token, str) or not token or "\n" in token or "\r" in token):
        raise CollectionError("The configured credential environment variable is unavailable or invalid.")
    if token and token in _json(config).decode("utf-8"):
        raise CollectionError("Keep the access credential out of collection settings.")
    origin = _url(config["url"])
    if token and origin[0] != "https":
        raise CollectionError("Use HTTPS when an access credential is configured.")
    owned_session = session is None
    client = requests.Session() if owned_session else session
    if owned_session:
        client.trust_env = False
    try:
        url = config["url"]
        query = dict(config["query"])
        pagination = config["pagination"]
        offset = pagination.get("start", 0)
        limits = config["limits"]
        total_bytes = 0
        total_records = 0
        pages = []
        records = []
        seen = set()
        while True:
            if len(pages) >= limits["max_pages"]:
                raise CollectionError("Pagination exceeded the configured page limit before completion.")
            if pagination["mode"] == "offset":
                query = {**config["query"], pagination["offset_param"]: offset,
                         pagination["limit_param"]: pagination["page_size"]}
            fingerprint = sha256(_json({"url": url, "query": query})).hexdigest()
            if fingerprint in seen:
                raise CollectionError("Pagination repeated a page address before completion.")
            seen.add(fingerprint)
            payload, raw, final_url = _page(client, url, query, token, limits, sleep, origin,
                                            limits["max_bytes"] - total_bytes)
            batch = _path(payload, config["records_path"])
            if not isinstance(batch, list) or not all(isinstance(item, dict) for item in batch):
                raise CollectionError("The configured records field must contain a list of JSON objects.")
            total_bytes += len(raw)
            total_records += len(batch)
            if total_records > limits["max_records"]:
                raise CollectionError("The collection exceeded its configured record limit.")
            pages.append({"page": len(pages) + 1, "request_sha256": fingerprint,
                          "response_sha256": sha256(raw).hexdigest(), "bytes": len(raw), "records": len(batch)})
            records.extend(_json(row) + b"\n" for row in batch)
            if pagination["mode"] == "none":
                break
            if pagination["mode"] == "next_url":
                next_url = _path(payload, pagination["next_path"])
                if next_url is None or next_url == "":
                    break
                if not isinstance(next_url, str):
                    raise CollectionError("The configured next page value must be a URL or an explicit empty value.")
                url = urljoin(final_url, next_url)
                _url(url, origin)
                query = None
            else:
                if not batch or pagination["stop_on"] == "short_page" and len(batch) < pagination["page_size"]:
                    break
                offset += pagination["page_size"]
        content = b"".join(records)
        if len(content) > limits["max_bytes"]:
            raise CollectionError("The collected records exceed the configured byte limit.")
        return _publish(output_dir, config, content, pages)
    finally:
        if owned_session:
            client.close()
