from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import requests

from . import __version__


BASE_V2 = "https://api.modrinth.com/v2"
BASE_V3 = "https://api.modrinth.com/v3"
DEFAULT_USER_AGENT = f"modrinth-collection-downloader/{__version__} (local-cli)"
COLLECTION_ID_RE = re.compile(r"^[A-Za-z0-9]+$")
MINECRAFT_PATCH_VERSION_RE = re.compile(r"^(\d+\.\d+)\.\d+$")


class ApiError(RuntimeError):
    def __init__(self, status_code: int, message: str, url: str | None = None):
        self.status_code = status_code
        self.message = message
        self.url = url
        super().__init__(message)


@dataclass(frozen=True)
class ProjectChunk:
    ids: list[str]


def parse_collection_id(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("Collection URL or ID is required.")

    parsed = urlparse(text)
    if parsed.scheme or parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        try:
            collection_index = parts.index("collection")
            collection_id = parts[collection_index + 1]
        except (ValueError, IndexError) as exc:
            raise ValueError("URL must contain /collection/{id}.") from exc
    else:
        collection_id = text.split("?", 1)[0].split("#", 1)[0].strip("/")

    if not COLLECTION_ID_RE.fullmatch(collection_id):
        raise ValueError("Collection ID must contain only letters and numbers.")
    return collection_id


def chunked(values: Iterable[str], size: int) -> Iterable[list[str]]:
    chunk: list[str] = []
    for value in values:
        chunk.append(value)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


class ModrinthClient:
    def __init__(
        self,
        *,
        token: str | None = None,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: int = 30,
        retries: int = 3,
        sleep=time.sleep,
    ) -> None:
        self.token = token
        self.session = requests.Session() if session is None else session
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = retries
        self.sleep = sleep

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": self.user_agent}
        if self.token:
            headers["Authorization"] = self.token
        return headers

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        request_kwargs = dict(kwargs)
        request_kwargs.setdefault("timeout", self.timeout)
        request_kwargs["headers"] = {
            **self._headers(),
            **request_kwargs.pop("headers", {}),
        }

        last_error: ApiError | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.request(method, url, **request_kwargs)
            except requests.RequestException as exc:
                last_error = ApiError(0, f"Network error: {exc}", url)
                if attempt < self.retries:
                    self.sleep(min(2**attempt, 8))
                    continue
                raise last_error from exc

            if response.status_code == 429 and attempt < self.retries:
                self.sleep(_rate_limit_sleep(response))
                continue

            if 500 <= response.status_code < 600 and attempt < self.retries:
                self.sleep(min(2**attempt, 8))
                continue

            if response.status_code >= 400:
                raise _api_error_from_response(response, url)
            return response

        if last_error:
            raise last_error
        raise ApiError(0, "Request failed.", url)

    def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        response = self._request("GET", url, params=params)
        return response.json()

    def get_current_user(self) -> dict[str, Any]:
        return self.get_json(f"{BASE_V2}/user")

    def get_collection(self, collection_id: str) -> dict[str, Any]:
        collection_id = quote(collection_id, safe="")
        return self.get_json(f"{BASE_V3}/collection/{collection_id}")

    def get_projects(self, project_ids: list[str], *, chunk_size: int = 100) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        for ids in chunked(project_ids, chunk_size):
            params = {"ids": json.dumps(ids, separators=(",", ":"))}
            data = self.get_json(f"{BASE_V2}/projects", params=params)
            if isinstance(data, list):
                projects.extend(data)
        return projects

    def list_project_versions(
        self,
        project_id: str,
        *,
        minecraft_versions: list[str] | None = None,
        loaders: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"include_changelog": "false"}
        if minecraft_versions:
            params["game_versions"] = json.dumps(
                expand_minecraft_version_query(minecraft_versions),
                separators=(",", ":"),
            )
        if loaders:
            params["loaders"] = json.dumps(loaders, separators=(",", ":"))

        project_id = quote(project_id, safe="")
        data = self.get_json(f"{BASE_V2}/project/{project_id}/version", params=params)
        return data if isinstance(data, list) else []


def expand_minecraft_version_query(minecraft_versions: Iterable[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for value in minecraft_versions:
        version = str(value).strip()
        if not version:
            continue
        for candidate in (version, _minor_minecraft_version(version)):
            if candidate and candidate not in seen:
                expanded.append(candidate)
                seen.add(candidate)
    return expanded


def _minor_minecraft_version(version: str) -> str | None:
    match = MINECRAFT_PATCH_VERSION_RE.fullmatch(version)
    if not match:
        return None
    return match.group(1)


def _rate_limit_sleep(response: requests.Response) -> float:
    value = response.headers.get("X-Ratelimit-Reset")
    try:
        return max(1.0, min(float(value), 60.0))
    except (TypeError, ValueError):
        return 5.0


def _api_error_from_response(response: requests.Response, url: str) -> ApiError:
    message = response.text or f"HTTP {response.status_code}"
    try:
        data = response.json()
    except ValueError:
        data = None

    if isinstance(data, dict):
        message = data.get("description") or data.get("error") or message

    if response.status_code == 401:
        message = f"Authentication failed or token is missing required scope. {message}"
    elif response.status_code == 404:
        message = f"Requested Modrinth item was not found or is not accessible. {message}"

    return ApiError(response.status_code, message, url)
