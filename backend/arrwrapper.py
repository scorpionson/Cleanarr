"""Radarr / Sonarr awareness for Cleanarr.

Plex can happily hold two copies of the same movie or episode while Radarr or
Sonarr only ever track ONE of them as the real file. The other is an orphan -
left behind by a failed upgrade, a manual import, or a post-processor that wrote
a file back after the *arr had already deleted it.

Cleanarr on its own cannot tell those apart: both copies look like valid media,
and the bigger / "higher quality" one is often the orphan. Deleting the tracked
copy instead of the orphan means the *arr immediately notices its file is gone.

This module asks the *arrs which file they actually track, and what that file's
custom format score is, so the UI can label each copy and the backend can refuse
to delete the one the *arr depends on.

Configuration (all optional - with no instances configured Cleanarr behaves
exactly as before):

    RADARR_URL / RADARR_API_KEY          a Radarr instance
    SONARR_URL / SONARR_API_KEY          a Sonarr instance
    ARR_INSTANCES                        advanced: several instances at once,
                                         "name|type|url|apikey" separated by ";"
                                         e.g. "Radarr|radarr|http://radarr:7878|abc;
                                               Radarr4K|radarr|http://radarr4k:7878|def"
    ARR_PATH_MATCH_DEPTH   (default 2)   trailing path components used to match a
                                         Plex path to an *arr path. Plex and the
                                         *arrs frequently mount the same library
                                         at different roots (/mnt/Movies vs
                                         /data/Movies), so full paths rarely match
                                         but the tail always does.
    ARR_CACHE_TTL          (default 300) seconds to cache *arr lookups
    ARR_TIMEOUT            (default 30)  per-request timeout in seconds
    ARR_VERIFY_SSL         (default 1)   set 0 for self-signed *arr certs
"""

import os
import threading
import time
from typing import Dict, List, Optional

import requests

from logger import get_logger

logger = get_logger(__name__)

RADARR = "radarr"
SONARR = "sonarr"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        logger.warning("Invalid %s, using default %s", name, default)
        return default


def normalise_path(path: str, depth: int) -> Optional[str]:
    """Reduce a path to its last `depth` components, lowercased.

    Plex and the *arrs commonly see the same library through different mounts, so
    we compare tails rather than whole paths. Depth 2 (parent folder + filename)
    is specific enough in practice because *arr folder names carry the title and
    an id, e.g. "Movie (2021) {tmdb-123}/Movie (2021) {tmdb-123} [Bluray].mkv".
    """
    if not path:
        return None
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    if not parts:
        return None
    return "/".join(parts[-depth:]).lower()


class ArrInstance:
    """One Radarr or Sonarr server."""

    def __init__(self, name: str, kind: str, url: str, api_key: str,
                 timeout: int, verify_ssl: bool):
        self.name = name
        self.kind = kind
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    def _get(self, path: str, params=None):
        try:
            response = requests.get(
                f"{self.url}/api/v3/{path}",
                params=params or {},
                headers={"X-Api-Key": self.api_key},
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            return response.json()
        except Exception as error:
            # An unreachable *arr must never break the duplicate list - callers
            # treat a None as "unknown" and the UI degrades to its old behaviour.
            logger.error("%s: GET %s failed: %s", self.name, path, error)
            return None


class ArrWrapper:
    """Answers "does an *arr track this file, and how good does it think it is?".

    Index building is deliberately cheap: one call per instance lists every
    tracked path, and the expensive per-file detail (custom format score) is
    fetched lazily, in bulk, only for the files actually on screen.
    """

    def __init__(self):
        self.depth = _env_int("ARR_PATH_MATCH_DEPTH", 2)
        self.ttl = _env_int("ARR_CACHE_TTL", 300)
        timeout = _env_int("ARR_TIMEOUT", 30)
        verify_ssl = os.environ.get("ARR_VERIFY_SSL", "1") != "0"

        # Whether the *arr-tracked copy should be ranked first in the UI's
        # default selection. On by default; set 0 to keep the original
        # resolution/size ordering and just show the badges.
        self.preselect = os.environ.get("ARR_PRESELECT", "1") != "0"

        self.instances = self._load_instances(timeout, verify_ssl)
        self._lock = threading.Lock()
        # normalised path -> {instance, kind, file_id, series_id, path}
        self._index: Dict[str, dict] = {}
        self._index_at = 0.0
        # file detail cache: (instance name, kind, file id) -> detail dict
        self._details: Dict[tuple, dict] = {}

        if self.instances:
            logger.info(
                "Arr integration enabled: %s (match depth %s, cache %ss)",
                ", ".join(f"{i.name}[{i.kind}]" for i in self.instances),
                self.depth, self.ttl,
            )
        else:
            logger.info("Arr integration disabled - no instances configured")

    @property
    def enabled(self) -> bool:
        return bool(self.instances)

    @staticmethod
    def _load_instances(timeout: int, verify_ssl: bool) -> List[ArrInstance]:
        instances: List[ArrInstance] = []

        for kind, url_var, key_var in (
            (RADARR, "RADARR_URL", "RADARR_API_KEY"),
            (SONARR, "SONARR_URL", "SONARR_API_KEY"),
        ):
            url = os.environ.get(url_var, "").strip()
            api_key = os.environ.get(key_var, "").strip()
            if url and api_key:
                instances.append(ArrInstance(kind.capitalize(), kind, url, api_key,
                                             timeout, verify_ssl))

        for entry in os.environ.get("ARR_INSTANCES", "").split(";"):
            entry = entry.strip()
            if not entry:
                continue
            fields = [f.strip() for f in entry.split("|")]
            if len(fields) != 4:
                logger.warning("Ignoring malformed ARR_INSTANCES entry: %s", entry)
                continue
            name, kind, url, api_key = fields
            kind = kind.lower()
            if kind not in (RADARR, SONARR):
                logger.warning("Ignoring ARR_INSTANCES entry with unknown type: %s", kind)
                continue
            instances.append(ArrInstance(name, kind, url, api_key, timeout, verify_ssl))

        return instances

    # ------------------------------------------------------------------ index

    def _build_index(self) -> Dict[str, dict]:
        """Map every *arr-tracked file path to the instance that tracks it.

        One request per instance. Sonarr has no bulk episodefile endpoint, so we
        index series here and resolve their episode files on demand.
        """
        index: Dict[str, dict] = {}

        for instance in self.instances:
            if instance.kind == RADARR:
                movies = instance._get("movie") or []
                for movie in movies:
                    movie_file = movie.get("movieFile") or {}
                    key = normalise_path(movie_file.get("path"), self.depth)
                    if key:
                        index[key] = {
                            "instance": instance,
                            "file_id": movie_file.get("id"),
                            "path": movie_file.get("path"),
                        }
                logger.debug("%s: indexed %s movie files", instance.name, len(movies))

            elif instance.kind == SONARR:
                series_list = instance._get("series") or []
                for series in series_list:
                    series_path = series.get("path") or ""
                    folder = normalise_path(series_path, 1)
                    if folder:
                        # Stored under a distinct namespace so a series folder can
                        # never collide with a media file key.
                        index[f"series::{folder}"] = {
                            "instance": instance,
                            "series_id": series.get("id"),
                            "path": series_path,
                        }
                logger.debug("%s: indexed %s series", instance.name, len(series_list))

        return index

    def _get_index(self) -> Dict[str, dict]:
        with self._lock:
            if not self._index or (time.time() - self._index_at) > self.ttl:
                self._index = self._build_index()
                self._index_at = time.time()
            return self._index

    def _resolve_series_episodes(self, entry: dict) -> Dict[str, dict]:
        """Fetch and cache one series' episode files, keyed by normalised path."""
        instance: ArrInstance = entry["instance"]
        series_id = entry["series_id"]
        cache_key = (instance.name, "series-files", series_id)

        cached = self._details.get(cache_key)
        if cached and (time.time() - cached["at"]) <= self.ttl:
            return cached["files"]

        files = {}
        for episode_file in instance._get("episodefile", {"seriesId": series_id}) or []:
            key = normalise_path(episode_file.get("path"), self.depth)
            if key:
                files[key] = episode_file
        self._details[cache_key] = {"at": time.time(), "files": files}
        return files

    # ----------------------------------------------------------------- lookup

    def lookup(self, file_path: str) -> Optional[dict]:
        """Return what the *arrs know about this file, or None if untracked.

        None means "no configured *arr tracks this path". That is NOT the same as
        "safe to delete" - the library may simply not be managed by an *arr - so
        callers should distinguish the two using `enabled`.
        """
        if not self.enabled or not file_path:
            return None

        key = normalise_path(file_path, self.depth)
        if not key:
            return None

        index = self._get_index()

        entry = index.get(key)
        if entry:
            return self._describe(entry, entry["file_id"], RADARR)

        # Episodes: find the owning series by walking up the path, then look the
        # episode file up within it.
        parts = [p for p in file_path.replace("\\", "/").split("/") if p]
        for depth in (2, 3):  # Series/file, Series/Season NN/file
            if len(parts) < depth:
                continue
            folder = parts[-depth].lower()
            series_entry = index.get(f"series::{folder}")
            if not series_entry:
                continue
            episode_file = self._resolve_series_episodes(series_entry).get(key)
            if episode_file:
                return self._describe(series_entry, episode_file.get("id"), SONARR,
                                      episode_file)
        return None

    def _describe(self, entry: dict, file_id, kind: str, prefetched=None) -> dict:
        instance: ArrInstance = entry["instance"]
        detail = prefetched or self._file_detail(instance, kind, file_id)
        quality = (((detail or {}).get("quality") or {}).get("quality") or {})
        return {
            "tracked": True,
            "instance": instance.name,
            "type": instance.kind,
            "path": (detail or {}).get("path") or entry.get("path"),
            "customFormatScore": (detail or {}).get("customFormatScore"),
            "customFormats": [f.get("name") for f in (detail or {}).get("customFormats") or []],
            "quality": quality.get("name"),
            "size": (detail or {}).get("size"),
        }

    def _file_detail(self, instance: ArrInstance, kind: str, file_id) -> Optional[dict]:
        """Per-file detail (custom format score, quality), cached by file id."""
        if file_id is None:
            return None
        cache_key = (instance.name, kind, file_id)
        cached = self._details.get(cache_key)
        if cached and (time.time() - cached["at"]) <= self.ttl:
            return cached["detail"]

        if kind == RADARR:
            # Radarr embeds movieFile in /movie but leaves customFormatScore null
            # there, so the score has to come from the moviefile endpoint.
            result = instance._get("moviefile", {"movieFileIds": file_id})
            detail = result[0] if isinstance(result, list) and result else None
        else:
            detail = None

        self._details[cache_key] = {"at": time.time(), "detail": detail}
        return detail

    def annotate_media(self, media: List[dict]) -> None:
        """Attach an `arr` block to each copy of a piece of content, in place.

        Adds, per copy:
            tracked   True if an *arr tracks this exact file
            unmanaged True when *arrs are configured but none tracks this file -
                      i.e. this copy is an orphan and the likely thing to delete
        """
        if not self.enabled:
            return
        for copy in media or []:
            info = None
            for part in copy.get("parts") or []:
                info = self.lookup(part.get("file"))
                if info:
                    break
            copy["arr"] = info or {"tracked": False, "unmanaged": True}

    def is_tracked(self, file_paths: List[str]) -> Optional[dict]:
        """Return the *arr record for the first tracked path, else None."""
        for file_path in file_paths:
            info = self.lookup(file_path)
            if info:
                return info
        return None


_wrapper: Optional[ArrWrapper] = None
_wrapper_lock = threading.Lock()


def get_arr_wrapper() -> ArrWrapper:
    """Process-wide singleton so the index and caches survive between requests."""
    global _wrapper
    with _wrapper_lock:
        if _wrapper is None:
            _wrapper = ArrWrapper()
        return _wrapper
