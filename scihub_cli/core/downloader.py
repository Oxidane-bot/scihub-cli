"""
Core downloader implementation with single responsibility.
"""

import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import requests

from ..config.auto_tuning import _merge_domain_list, load_auto_tuning
from ..config.domains import (
    ACADEMIC_HOST_MARKERS,
    FAST_FAIL_LIGHTWEIGHT_BYPASS_HOSTS,
    FAST_FAIL_PAGE_BYPASS_HOSTS,
    FAST_FAIL_PAGE_BYPASS_SCIHUB_MARKERS,
    FAST_FAIL_SKIP_CHALLENGE_DOWNLOAD_HOSTS,
    FAST_FAIL_SKIP_PAGE_BYPASS_HOSTS,
    NON_ACADEMIC_HOST_MARKERS,
)
from ..config.settings import settings
from ..network.session import BasicSession
from ..utils.logging import get_logger
from ..utils.retry import (
    DownloadRetryConfig,
    PermanentError,
    RetryableError,
    classify_http_error,
    retry_with_classification,
)
from .challenge_detection import (
    derive_alternate_pdf_urls,
    derive_landing_prefetch_url,
    is_akamai_access_denied_html,
    is_auth_or_paywall_html,
    is_challenge_html,
    is_hard_challenge_block_html,
    is_scihub_host,
    looks_like_pdf_download_path,
    normalize_download_url,
    normalize_recovery_url,
    should_fast_fail_probe_403_html,
)
from .pdf_link_extractor import extract_ranked_pdf_candidates

logger = get_logger(__name__)


class HTMLResponseError(PermanentError):
    """Raised when a download endpoint serves HTML instead of a PDF."""

    def __init__(
        self,
        message: str,
        *,
        url: str,
        status_code: int | None,
        content_type: str | None,
    ):
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.content_type = content_type


class FileDownloader:
    """Handles pure file downloading operations."""

    _FAST_FAIL_LIGHTWEIGHT_BYPASS_HOSTS = FAST_FAIL_LIGHTWEIGHT_BYPASS_HOSTS
    _FAST_FAIL_SKIP_CHALLENGE_DOWNLOAD_HOSTS = FAST_FAIL_SKIP_CHALLENGE_DOWNLOAD_HOSTS
    _FAST_FAIL_PAGE_BYPASS_HOSTS = FAST_FAIL_PAGE_BYPASS_HOSTS
    _FAST_FAIL_PAGE_BYPASS_SCIHUB_MARKERS = FAST_FAIL_PAGE_BYPASS_SCIHUB_MARKERS
    _FAST_FAIL_SKIP_PAGE_BYPASS_HOSTS = FAST_FAIL_SKIP_PAGE_BYPASS_HOSTS
    _ACADEMIC_HOST_MARKERS = ACADEMIC_HOST_MARKERS
    _NON_ACADEMIC_HOST_MARKERS = NON_ACADEMIC_HOST_MARKERS
    _FAST_FAIL_DEADLINE_MIN_SECONDS_FOR_GRACE = 5.0
    _FAST_FAIL_DEADLINE_PROGRESS_MIN_BYTES = 256 * 1024
    _FAST_FAIL_DEADLINE_PROGRESS_GRACE_SECONDS = 6.0
    _FAST_FAIL_DEADLINE_MAX_EXTENSIONS = 1

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = None,
        fast_fail: bool = False,
        retries: int | None = None,
        download_deadline_seconds: float | None = None,
    ):
        self.session = session or BasicSession(timeout or settings.timeout)
        self.timeout = timeout or settings.timeout
        self.fast_fail = fast_fail

        # Retry configuration for downloads
        self.retry_config = DownloadRetryConfig()
        if retries is not None:
            max_attempts = max(1, int(retries))
            if self.fast_fail:
                max_attempts = min(max_attempts, 1)
            self.retry_config.max_attempts = max_attempts
        elif self.fast_fail:
            # Fast-fail mode prefers quick convergence; keep a single attempt.
            self.retry_config.max_attempts = 1
        if self.retry_config.max_attempts <= 1:
            self.retry_config.base_delay = 0.0
            self.retry_config.max_delay = 0.0
        elif self.fast_fail:
            self.retry_config.base_delay = min(self.retry_config.base_delay, 0.5)
            self.retry_config.max_delay = min(self.retry_config.max_delay, 2.0)

        if download_deadline_seconds is None:
            if self.fast_fail:
                download_deadline_seconds = max(10.0, float(self.timeout) * 1.5)
            else:
                download_deadline_seconds = max(30.0, float(self.timeout) * 6.0)
        self.download_deadline_seconds = (
            float(download_deadline_seconds)
            if download_deadline_seconds is not None and download_deadline_seconds > 0
            else None
        )

        # Rate limiting for curl_cffi bypass (per-domain)
        self._last_bypass_time = {}  # domain -> timestamp
        self._bypass_delay = 0.2 if self.fast_fail else 2.0  # seconds between bypass requests
        self._trace_local = threading.local()
        self._prefetch_cache_local = threading.local()
        self._html_recovery_max_depth = 0 if self.fast_fail else 1
        self._html_recovery_min_score = 750
        self._fast_fail_html_recovery_min_score = 1000
        self._fast_fail_html_recovery_max_candidates = 3

        # Auto-tuning: merge per-run domain overrides into host lists.
        rules = load_auto_tuning()
        if isinstance(rules, dict):
            self.__class__._FAST_FAIL_LIGHTWEIGHT_BYPASS_HOSTS = _merge_domain_list(
                self._FAST_FAIL_LIGHTWEIGHT_BYPASS_HOSTS,
                add=rules.get("fast_fail_lightweight_bypass_hosts_add"),
                drop=rules.get("fast_fail_lightweight_bypass_hosts_drop"),
            )
            self.__class__._FAST_FAIL_SKIP_CHALLENGE_DOWNLOAD_HOSTS = _merge_domain_list(
                self._FAST_FAIL_SKIP_CHALLENGE_DOWNLOAD_HOSTS,
                add=rules.get("fast_fail_skip_challenge_download_hosts_add"),
                drop=rules.get("fast_fail_skip_challenge_download_hosts_drop"),
            )
            self.__class__._FAST_FAIL_PAGE_BYPASS_HOSTS = _merge_domain_list(
                self._FAST_FAIL_PAGE_BYPASS_HOSTS,
                add=rules.get("fast_fail_page_bypass_hosts_add"),
                drop=rules.get("fast_fail_page_bypass_hosts_drop"),
            )
            self.__class__._FAST_FAIL_SKIP_PAGE_BYPASS_HOSTS = _merge_domain_list(
                self._FAST_FAIL_SKIP_PAGE_BYPASS_HOSTS,
                add=rules.get("fast_fail_skip_page_bypass_hosts_add"),
                drop=rules.get("fast_fail_skip_page_bypass_hosts_drop"),
            )
            self.__class__._ACADEMIC_HOST_MARKERS = _merge_domain_list(
                self._ACADEMIC_HOST_MARKERS,
                add=rules.get("academic_host_markers_add"),
                drop=rules.get("academic_host_markers_drop"),
            )
            self.__class__._NON_ACADEMIC_HOST_MARKERS = _merge_domain_list(
                self._NON_ACADEMIC_HOST_MARKERS,
                add=rules.get("non_academic_host_markers_add"),
                drop=rules.get("non_academic_host_markers_drop"),
            )

    def push_trace_context(
        self,
        context: dict[str, Any],
        *,
        html_snapshot_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Bind per-call diagnostic context for get_page_content."""
        self._trace_local.context = dict(context)
        self._trace_local.html_snapshot_callback = html_snapshot_callback

    def clear_trace_context(self) -> None:
        """Clear per-call diagnostic context."""
        if hasattr(self._trace_local, "context"):
            del self._trace_local.context
        if hasattr(self._trace_local, "html_snapshot_callback"):
            del self._trace_local.html_snapshot_callback

    def _emit_html_snapshot(
        self,
        *,
        url: str,
        status_code: int | None,
        html: str | None,
        fetcher: str,
        error: str | None = None,
    ) -> None:
        runtime_events = getattr(self._trace_local, "download_html_events", None)
        if isinstance(runtime_events, list):
            runtime_events.append(
                {
                    "url": url,
                    "status_code": status_code,
                    "fetcher": fetcher,
                    "error": error,
                    "html": html,
                }
            )

        callback = getattr(self._trace_local, "html_snapshot_callback", None)
        if not callable(callback):
            return

        context = getattr(self._trace_local, "context", {}) or {}
        payload = {
            **context,
            "url": url,
            "status_code": status_code,
            "fetcher": fetcher,
            "error": error,
            "html": html,
        }
        try:
            callback(payload)
        except Exception as e:
            logger.debug(f"HTML snapshot callback failed: {e}")

    @staticmethod
    def _extract_html_for_snapshot(response: Any) -> str | None:
        try:
            content_type = (response.headers.get("Content-Type", "") or "").lower()
        except Exception:
            content_type = ""
        try:
            text = response.text if isinstance(response.text, str) else None
        except Exception:
            text = None
        if not text:
            return None
        lowered = text.lower()
        if "html" in content_type:
            return text
        if "<html" in lowered or "<!doctype" in lowered or "<body" in lowered:
            return text
        return None

    def download_file(
        self,
        url: str,
        output_path: str,
        progress_callback: Callable[[int, int | None], None] | None = None,
        *,
        _html_recovery_depth: int = 0,
        _visited_urls: set[str] | None = None,
    ) -> tuple[bool, str | None]:
        """
        Download a file from URL to output path with automatic retry.

        Args:
            url: URL to download from
            output_path: Path to save file

        Returns:
            Tuple of (success: bool, error_msg: Optional[str])
        """
        logger.info(f"Downloading to {output_path}")
        url = normalize_download_url(url)
        # Ensure output directory exists before attempting download
        import os

        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        if self._should_fast_fail_non_academic_url(url):
            error_msg = "Skipped non-academic URL in fast-fail mode"
            logger.info(f"{error_msg}: {url}")
            return False, error_msg
        if self._should_fast_fail_skip_challenge_pdf_url(url):
            error_msg = "Skipped challenge-heavy PDF URL in fast-fail mode"
            logger.info(f"{error_msg}: {url}")
            return False, error_msg

        visited_urls = _visited_urls if _visited_urls is not None else set()
        normalized_url = normalize_recovery_url(url)
        if normalized_url:
            visited_urls.add(normalized_url)

        previous_events = getattr(self._trace_local, "download_html_events", None)
        self._trace_local.download_html_events = []

        try:

            def _attempt_download():
                landing_url = derive_landing_prefetch_url(url)
                if landing_url:
                    self._prefetch_landing_page(
                        landing_url=landing_url,
                        request_timeout=min(float(self.timeout), 8.0),
                    )
                deadline_ts = self._new_download_deadline()
                return self._download_once(
                    url,
                    output_path,
                    progress_callback,
                    deadline_ts=deadline_ts,
                )

            try:
                return retry_with_classification(
                    _attempt_download, self.retry_config, f"download from {url}"
                )
            except PermanentError as e:
                # Check if it's a 403 or HTML response - might be CDN protection/challenge page.
                error_msg = str(e)
                alternate_success = self._try_alternate_pdf_endpoints(
                    url=url,
                    output_path=output_path,
                    progress_callback=progress_callback,
                    error_msg=error_msg,
                    visited_urls=visited_urls,
                    _html_recovery_depth=_html_recovery_depth,
                )
                if alternate_success:
                    return True, None
                if self.fast_fail:
                    fallback_success, fallback_error = self._try_fast_fail_lightweight_bypass(
                        url=url,
                        output_path=output_path,
                        progress_callback=progress_callback,
                        trigger_error=error_msg,
                    )
                    if fallback_success:
                        return True, None
                    if fallback_error:
                        logger.debug(f"Fast-fail lightweight bypass failed: {fallback_error}")
                    html_events = self._collect_html_events_for_recovery()
                    recovered, recovery_error = self._try_fast_fail_html_recovery(
                        output_path=output_path,
                        progress_callback=progress_callback,
                        html_events=html_events,
                        visited_urls=visited_urls,
                    )
                    if recovered:
                        return True, None
                    if recovery_error:
                        logger.debug(f"Fast-fail HTML recovery failed: {recovery_error}")
                    logger.info("Fast-fail enabled: skipping bypass and HTML recovery")
                    logger.error(f"Permanent failure: {error_msg}")
                    return False, error_msg

                if isinstance(e, HTMLResponseError) or "403" in error_msg:
                    if "403" in error_msg:
                        logger.warning("Got 403 error, attempting cloudscraper bypass...")
                    else:
                        logger.warning("Got HTML response, attempting cloudscraper bypass...")
                    success, bypass_error = self._download_with_cloudscraper(
                        url, output_path, progress_callback
                    )
                    if success:
                        logger.info("Successfully downloaded using cloudscraper bypass")
                        return True, None
                    if bypass_error:
                        logger.warning(f"cloudscraper bypass also failed: {bypass_error}")

                    if "403" in error_msg:
                        logger.warning("Got 403 error, attempting curl_cffi bypass...")
                    else:
                        logger.warning("Got HTML response, attempting curl_cffi bypass...")
                    success, bypass_error = self._download_with_curl_cffi(
                        url, output_path, progress_callback
                    )
                    if success:
                        logger.info("Successfully downloaded using curl_cffi bypass")
                        return True, None
                    if bypass_error:
                        logger.warning(f"curl_cffi bypass also failed: {bypass_error}")

                if _html_recovery_depth < self._html_recovery_max_depth:
                    html_events = self._collect_html_events_for_recovery()
                    recovered, recovery_error = self._recover_from_html_candidates(
                        output_path=output_path,
                        progress_callback=progress_callback,
                        html_events=html_events,
                        visited_urls=visited_urls,
                        next_depth=_html_recovery_depth + 1,
                    )
                    if recovered:
                        return True, None
                    if recovery_error:
                        error_msg = f"{error_msg}. {recovery_error}"

                logger.error(f"Permanent failure: {error_msg}")
                return False, error_msg
            except Exception as e:
                # All retries exhausted
                error_msg = str(e)
                fallback_success, fallback_error = self._try_fast_fail_lightweight_bypass(
                    url=url,
                    output_path=output_path,
                    progress_callback=progress_callback,
                    trigger_error=error_msg,
                )
                if fallback_success:
                    return True, None
                if fallback_error:
                    logger.debug(f"Fast-fail lightweight bypass failed: {fallback_error}")
                html_events = self._collect_html_events_for_recovery()
                if html_events:
                    if self.fast_fail:
                        recovered, recovery_error = self._try_fast_fail_html_recovery(
                            output_path=output_path,
                            progress_callback=progress_callback,
                            html_events=html_events,
                            visited_urls=visited_urls,
                        )
                        if recovered:
                            return True, None
                        if recovery_error:
                            logger.debug(f"Fast-fail HTML recovery failed: {recovery_error}")
                    elif _html_recovery_depth < self._html_recovery_max_depth:
                        recovered, recovery_error = self._recover_from_html_candidates(
                            output_path=output_path,
                            progress_callback=progress_callback,
                            html_events=html_events,
                            visited_urls=visited_urls,
                            next_depth=_html_recovery_depth + 1,
                        )
                        if recovered:
                            return True, None
                        if recovery_error:
                            error_msg = f"{error_msg}. {recovery_error}"
                logger.error(f"Download failed after all retries: {error_msg}")
                return False, error_msg
        finally:
            if previous_events is None:
                if hasattr(self._trace_local, "download_html_events"):
                    del self._trace_local.download_html_events
            else:
                self._trace_local.download_html_events = previous_events

    def _try_alternate_pdf_endpoints(
        self,
        *,
        url: str,
        output_path: str,
        progress_callback: Callable[[int, int | None], None] | None,
        error_msg: str,
        visited_urls: set[str],
        _html_recovery_depth: int,
    ) -> bool:
        lowered = (error_msg or "").lower()
        if not any(token in lowered for token in ("403", "server returned html")):
            return False
        alternates = derive_alternate_pdf_urls(url)
        if not alternates:
            return False
        for candidate in alternates:
            normalized = normalize_recovery_url(candidate)
            if not normalized or normalized in visited_urls:
                continue
            visited_urls.add(normalized)
            logger.info(f"[Retry] Trying alternate PDF endpoint: {candidate}")
            success, _error = self.download_file(
                candidate,
                output_path,
                progress_callback,
                _html_recovery_depth=_html_recovery_depth + 1,
                _visited_urls=visited_urls,
            )
            if success:
                logger.info(f"[Retry] Alternate endpoint succeeded: {candidate}")
                return True
        return False

    def _collect_html_events_for_recovery(self) -> list[dict[str, Any]]:
        events = getattr(self._trace_local, "download_html_events", None)
        if not isinstance(events, list):
            return []
        out: list[dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            html = event.get("html")
            if not isinstance(html, str) or not html.strip():
                continue
            if is_scihub_host(event.get("url", "")):
                continue
            out.append(event)
        return out

    def _recover_from_html_candidates(
        self,
        *,
        output_path: str,
        progress_callback: Callable[[int, int | None], None] | None,
        html_events: list[dict[str, Any]],
        visited_urls: set[str],
        next_depth: int,
    ) -> tuple[bool, str | None]:
        if not html_events:
            return False, None

        ranked_candidates: dict[str, int] = {}
        order: dict[str, int] = {}
        order_counter = 0
        for event in html_events:
            html = event.get("html")
            base_url = event.get("url")
            if not isinstance(html, str) or not isinstance(base_url, str):
                continue
            for score, candidate in extract_ranked_pdf_candidates(html, base_url):
                if score < self._html_recovery_min_score:
                    continue
                normalized = normalize_recovery_url(candidate)
                if not normalized or normalized in visited_urls:
                    continue
                if normalized not in order:
                    order[normalized] = order_counter
                    order_counter += 1
                best = ranked_candidates.get(normalized, -1)
                if score > best:
                    ranked_candidates[normalized] = score

        if not ranked_candidates:
            return False, None

        candidates = sorted(
            ranked_candidates.items(),
            key=lambda item: (-item[1], order[item[0]]),
        )
        errors: list[tuple[str, str]] = []

        for candidate, _score in candidates:
            visited_urls.add(candidate)
            logger.info(f"[HTML Recovery] Trying extracted candidate: {candidate}")
            success, error = self.download_file(
                candidate,
                output_path,
                progress_callback,
                _html_recovery_depth=next_depth,
                _visited_urls=visited_urls,
            )
            if success:
                logger.info(
                    f"[HTML Recovery] Successfully downloaded via extracted candidate: {candidate}"
                )
                return True, None
            errors.append((candidate, error or "Download failed"))

        detail = "; ".join(f"{candidate} => {reason}" for candidate, reason in errors)
        return (
            False,
            f"HTML recovery tried {len(errors)} extracted candidate URLs: {detail}",
        )

    def _try_fast_fail_html_recovery(
        self,
        *,
        output_path: str,
        progress_callback: Callable[[int, int | None], None] | None,
        html_events: list[dict[str, Any]],
        visited_urls: set[str],
    ) -> tuple[bool, str | None]:
        if not self.fast_fail:
            return False, None
        if not html_events:
            return False, None

        ranked_candidates: dict[str, int] = {}
        order: dict[str, int] = {}
        order_counter = 0
        for event in html_events:
            html = event.get("html")
            base_url = event.get("url")
            if not isinstance(html, str) or not isinstance(base_url, str):
                continue
            for score, candidate in extract_ranked_pdf_candidates(html, base_url):
                if score < self._fast_fail_html_recovery_min_score:
                    continue
                normalized = normalize_recovery_url(candidate)
                if not normalized or normalized in visited_urls:
                    continue
                if normalized not in order:
                    order[normalized] = order_counter
                    order_counter += 1
                best = ranked_candidates.get(normalized, -1)
                if score > best:
                    ranked_candidates[normalized] = score

        if not ranked_candidates:
            return False, None

        candidates = sorted(
            ranked_candidates.items(),
            key=lambda item: (-item[1], order[item[0]]),
        )
        errors: list[tuple[str, str]] = []

        for candidate, _score in candidates[: self._fast_fail_html_recovery_max_candidates]:
            visited_urls.add(candidate)
            logger.info(f"[Fast-Fail HTML] Trying extracted candidate: {candidate}")
            success, error = self.download_file(
                candidate,
                output_path,
                progress_callback,
                _html_recovery_depth=self._html_recovery_max_depth + 1,
                _visited_urls=visited_urls,
            )
            if success:
                logger.info(
                    f"[Fast-Fail HTML] Successfully downloaded via extracted candidate: {candidate}"
                )
                return True, None
            errors.append((candidate, error or "Download failed"))

        detail = "; ".join(f"{candidate} => {reason}" for candidate, reason in errors)
        return (
            False,
            f"fast-fail HTML recovery tried {len(errors)} extracted candidate URLs: {detail}",
        )

    def _try_fast_fail_lightweight_bypass(
        self,
        *,
        url: str,
        output_path: str,
        progress_callback: Callable[[int, int | None], None] | None,
        trigger_error: str,
    ) -> tuple[bool, str | None]:
        if not self._should_try_fast_fail_lightweight_bypass(url, trigger_error):
            return False, None
        if self._should_skip_fast_fail_bypass_for_hard_block(url, trigger_error):
            return False, "Hard access block detected; skipping lightweight bypass"
        logger.info(f"Fast-fail lightweight bypass attempt (curl_cffi): {url}")
        success, error = self._download_with_curl_cffi(url, output_path, progress_callback)
        if success:
            return True, None
        if not self._should_retry_fast_fail_lightweight_bypass(error, url=url):
            return False, error
        logger.info(f"Fast-fail lightweight bypass retry (curl_cffi): {url}")
        retry_success, retry_error = self._download_with_curl_cffi(
            url, output_path, progress_callback
        )
        if retry_success:
            return True, None
        return False, retry_error or error

    def _should_try_fast_fail_lightweight_bypass(self, url: str, error_msg: str) -> bool:
        if not self.fast_fail:
            return False
        parsed = urlparse((url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        host = parsed.netloc.lower()
        if not any(marker in host for marker in self._FAST_FAIL_LIGHTWEIGHT_BYPASS_HOSTS):
            return False
        path_lower = parsed.path.lower()
        query_lower = (parsed.query or "").lower()
        pdf_like = (
            path_lower.endswith(".pdf")
            or "/pdf" in path_lower
            or ".pdf" in query_lower
            or (
                "papers.ssrn.com" in host
                and "delivery.cfm" in path_lower
                and "abstractid" in query_lower
            )
        )
        if not pdf_like:
            return False
        lowered = (error_msg or "").lower()
        if (
            "server returned html" in lowered
            and "mdpi.com" not in host
            and "mdpi-res.com" not in host
        ):
            return False
        return any(
            token in lowered
            for token in (
                "403",
                "timeout",
                "connection error",
                "server returned html",
                "download deadline exceeded",
                "http 429",
                "http 5",
            )
        )

    def _should_retry_fast_fail_lightweight_bypass(
        self, error_msg: str | None, *, url: str | None = None
    ) -> bool:
        lowered = (error_msg or "").lower()
        if "http 403" in lowered:
            parsed = urlparse((url or "").strip())
            host = parsed.netloc.lower()
            if any(
                marker in host
                for marker in (
                    "mdpi.com",
                    "mdpi-res.com",
                    "res.mdpi.com",
                )
            ):
                events = getattr(self._trace_local, "download_html_events", None)
                if isinstance(events, list):
                    for event in reversed(events):
                        if not isinstance(event, dict):
                            continue
                        if event.get("status_code") != 403:
                            continue
                        html = event.get("html")
                        if isinstance(html, str) and is_akamai_access_denied_html(html):
                            # Hard block: avoid wasting time on duplicate retries.
                            return False
                        break
                # Soft/unknown 403s can occasionally recover on immediate retry.
                return True
        return any(
            token in lowered
            for token in (
                "timeout",
                "timed out",
                "connection error",
                "temporarily unavailable",
                "http 429",
                "http 5",
                "ssl",
                "eof",
            )
        )

    def _should_skip_fast_fail_bypass_for_hard_block(self, url: str, trigger_error: str) -> bool:
        if "403" not in (trigger_error or "").lower():
            return False
        events = getattr(self._trace_local, "download_html_events", None)
        if not isinstance(events, list):
            return False
        for event in reversed(events):
            if not isinstance(event, dict):
                continue
            if event.get("status_code") != 403:
                continue
            html = event.get("html")
            if isinstance(html, str) and is_akamai_access_denied_html(html):
                logger.info("Fast-fail detected Akamai hard block; bypass skipped")
                return True
            break
        return False

    def probe_pdf_url(self, url: str) -> bool:
        """
        Probe a URL to see if it appears to serve a PDF without downloading it.

        Returns:
            True if the response looks like a PDF, False otherwise.
        """
        response = None
        try:
            response = self.session.get(url, timeout=self.timeout, stream=True)

            if response.status_code == 403:
                content_type = (response.headers.get("Content-Type", "") or "").lower()
                response_text = response.text if isinstance(response.text, str) else ""
                if "html" in content_type and should_fast_fail_probe_403_html(response_text):
                    logger.debug(f"Probe got gated/challenge HTML on 403 for {url}; rejecting")
                    return False
                logger.debug(f"Probe got 403 for {url}; treating as potentially valid PDF")
                return True
            if response.status_code != 200:
                return False

            content_type = response.headers.get("Content-Type", "")
            if "html" in content_type.lower():
                return False

            header = b""
            for chunk in response.iter_content(chunk_size=4):
                header += chunk
                if len(header) >= 4:
                    break

            return header[:4] == b"%PDF"
        except Exception as e:
            logger.debug(f"Probe failed for {url}: {e}")
            return False
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()

    def _download_once(
        self,
        url: str,
        output_path: str,
        progress_callback: Callable[[int, int | None], None] | None = None,
        *,
        deadline_ts: float | None = None,
    ) -> tuple[bool, str | None]:
        """
        Single download attempt with error classification.

        Raises:
            PermanentError: For 404, 403, invalid PDF content
            RetryableError: For timeouts, 408/429/5xx errors, connection issues
        """
        import os
        import shutil
        import tempfile

        try:
            self._check_deadline(deadline_ts)
            response = self.session.get(
                url,
                timeout=self._effective_timeout(deadline_ts),
                stream=True,
            )

            # Classify HTTP errors
            if response.status_code == 404:
                self._emit_html_snapshot(
                    url=url,
                    status_code=response.status_code,
                    html=response.text
                    if "html" in response.headers.get("Content-Type", "").lower()
                    else None,
                    fetcher="requests",
                    error="File not found (404)",
                )
                raise PermanentError("File not found (404)")
            elif response.status_code == 403:
                self._emit_html_snapshot(
                    url=url,
                    status_code=response.status_code,
                    html=response.text
                    if "html" in response.headers.get("Content-Type", "").lower()
                    else None,
                    fetcher="requests",
                    error="Access denied (403)",
                )
                raise PermanentError("Access denied (403)")
            elif response.status_code == 202:
                self._emit_html_snapshot(
                    url=url,
                    status_code=response.status_code,
                    html=self._extract_html_for_snapshot(response),
                    fetcher="requests",
                    error="HTTP 202",
                )
                raise RetryableError("HTTP 202")
            elif response.status_code != 200:
                self._emit_html_snapshot(
                    url=url,
                    status_code=response.status_code,
                    html=self._extract_html_for_snapshot(response),
                    fetcher="requests",
                    error=f"HTTP {response.status_code}",
                )
                if classify_http_error(response.status_code):
                    raise RetryableError(f"HTTP {response.status_code}")
                raise PermanentError(f"HTTP {response.status_code}")

            # Check content type
            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower() and "octet-stream" not in content_type.lower():
                logger.warning(f"Response is not a PDF: {content_type}")
                # If it's clearly HTML, reject it (permanent)
                if "html" in content_type.lower():
                    self._emit_html_snapshot(
                        url=url,
                        status_code=response.status_code,
                        html=response.text,
                        fetcher="requests",
                        error=f"Server returned HTML instead of PDF (Content-Type: {content_type})",
                    )
                    raise HTMLResponseError(
                        f"Server returned HTML instead of PDF (Content-Type: {content_type})",
                        url=url,
                        status_code=response.status_code,
                        content_type=content_type,
                    )

            # Download to temporary location first
            temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf")
            total_header = response.headers.get("Content-Length")
            total_bytes = int(total_header) if total_header and total_header.isdigit() else None
            bytes_downloaded = 0
            deadline_state = {"ts": deadline_ts, "extensions": 0}

            def _check_deadline_with_progress() -> None:
                current_deadline = deadline_state["ts"]
                if current_deadline is None:
                    return
                now = time.monotonic()
                if now <= current_deadline:
                    return
                if self._can_extend_deadline_for_active_fast_fail_download(
                    url=url,
                    bytes_downloaded=bytes_downloaded,
                    extensions_used=deadline_state["extensions"],
                ):
                    deadline_state["ts"] = now + self._FAST_FAIL_DEADLINE_PROGRESS_GRACE_SECONDS
                    deadline_state["extensions"] += 1
                    logger.info(
                        "[Fast-fail] Extending active download deadline by %.1fs for %s",
                        self._FAST_FAIL_DEADLINE_PROGRESS_GRACE_SECONDS,
                        url,
                    )
                    return
                self._check_deadline(current_deadline)

            try:
                with os.fdopen(temp_fd, "wb") as f:
                    for chunk in response.iter_content(chunk_size=settings.CHUNK_SIZE):
                        _check_deadline_with_progress()
                        if chunk:
                            f.write(chunk)
                            bytes_downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(bytes_downloaded, total_bytes)

                # Verify it's actually a PDF by checking file header
                with open(temp_path, "rb") as f:
                    header = f.read(4)
                    if header != b"%PDF":
                        os.unlink(temp_path)
                        raise PermanentError(
                            "Downloaded file is not a valid PDF (missing PDF header)"
                        )

                # If valid, move to final destination
                _check_deadline_with_progress()
                shutil.move(temp_path, output_path)
                return True, None

            except (PermanentError, RetryableError):
                # Clean up temp file and re-raise
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
            except Exception:
                # Clean up temp file on other errors
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

        except requests.Timeout as e:
            raise RetryableError("Download timeout") from e
        except requests.ConnectionError as e:
            raise RetryableError(f"Connection error: {e}") from e
        except (PermanentError, RetryableError):
            # Re-raise classified exceptions
            raise
        except Exception as e:
            # Unknown errors are considered retryable (conservative)
            raise RetryableError(f"Download error: {e}") from e

    def _download_with_cloudscraper(
        self,
        url: str,
        output_path: str,
        progress_callback: Callable[[int, int | None], None] | None = None,
    ) -> tuple[bool, str | None]:
        """Bypass Cloudflare challenges using cloudscraper."""
        try:
            import cloudscraper
        except ImportError:
            return False, "cloudscraper not installed (pip install cloudscraper)"

        import os
        import shutil
        import tempfile

        try:
            scraper = cloudscraper.create_scraper()
            response = scraper.get(url, timeout=self.timeout, stream=True)

            if response.status_code != 200:
                self._emit_html_snapshot(
                    url=url,
                    status_code=response.status_code,
                    html=response.text
                    if "html" in response.headers.get("Content-Type", "").lower()
                    else None,
                    fetcher="cloudscraper",
                    error=f"HTTP {response.status_code}",
                )
                return False, f"HTTP {response.status_code}"

            content_type = response.headers.get("Content-Type", "")
            if "html" in content_type.lower():
                self._emit_html_snapshot(
                    url=url,
                    status_code=response.status_code,
                    html=response.text,
                    fetcher="cloudscraper",
                    error=f"Server returned HTML (Content-Type: {content_type})",
                )
                return False, f"Server returned HTML (Content-Type: {content_type})"

            temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf")
            total_header = response.headers.get("Content-Length")
            total_bytes = int(total_header) if total_header and total_header.isdigit() else None
            bytes_downloaded = 0

            try:
                with os.fdopen(temp_fd, "wb") as f:
                    for chunk in response.iter_content(chunk_size=settings.CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                            bytes_downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(bytes_downloaded, total_bytes)

                with open(temp_path, "rb") as f:
                    header = f.read(4)
                    if header != b"%PDF":
                        os.unlink(temp_path)
                        return False, "Downloaded file is not a valid PDF"

                shutil.move(temp_path, output_path)
                return True, None

            except Exception:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

        except Exception as e:
            logger.debug(f"[cloudscraper] Download failed: {e}")
            return False, str(e)

    def _download_with_curl_cffi(
        self,
        url: str,
        output_path: str,
        progress_callback: Callable[[int, int | None], None] | None = None,
    ) -> tuple[bool, str | None]:
        """
        Bypass CDN protection using curl_cffi with browser impersonation.

        This is used as a fallback when regular requests get 403 errors,
        typically from Akamai or other CDN protection systems.

        Implements per-domain rate limiting to be respectful to servers.

        Args:
            url: URL to download from
            output_path: Path to save file

        Returns:
            Tuple of (success: bool, error_msg: Optional[str])
        """
        try:
            from curl_cffi import requests as cf_requests
        except ImportError:
            return False, "curl_cffi not installed (pip install curl-cffi)"

        import os
        import shutil
        import tempfile
        from urllib.parse import urlparse

        try:
            # Extract domain for rate limiting
            domain = urlparse(url).netloc

            # Rate limiting: wait if we recently made a request to this domain
            if domain in self._last_bypass_time:
                elapsed = time.time() - self._last_bypass_time[domain]
                if elapsed < self._bypass_delay:
                    wait_time = self._bypass_delay - elapsed
                    logger.info(f"[curl_cffi] Rate limiting: waiting {wait_time:.1f}s for {domain}")
                    time.sleep(wait_time)

            # Use Chrome 110 impersonation - works well for most CDNs
            logger.debug(f"[curl_cffi] Downloading with Chrome 110 impersonation: {url}")
            session = cf_requests.Session()
            landing_url = derive_landing_prefetch_url(url)
            referer = landing_url or url
            if landing_url:
                self._prefetch_landing_page_curl_cffi(
                    session=session,
                    landing_url=landing_url,
                )
            response = session.get(
                url,
                impersonate="chrome110",
                timeout=self.timeout,
                headers={"Referer": referer},
            )
            self._last_bypass_time[domain] = time.time()

            if response.status_code != 200:
                self._emit_html_snapshot(
                    url=url,
                    status_code=response.status_code,
                    html=response.text
                    if "html" in response.headers.get("Content-Type", "").lower()
                    else None,
                    fetcher="curl_cffi",
                    error=f"HTTP {response.status_code}",
                )
                return False, f"HTTP {response.status_code}"

            # Check content type
            content_type = response.headers.get("Content-Type", "")
            if "html" in content_type.lower():
                self._emit_html_snapshot(
                    url=url,
                    status_code=response.status_code,
                    html=response.text,
                    fetcher="curl_cffi",
                    error=f"Server returned HTML (Content-Type: {content_type})",
                )
                return False, f"Server returned HTML (Content-Type: {content_type})"

            # Download to temporary location first
            temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf")

            try:
                with os.fdopen(temp_fd, "wb") as f:
                    f.write(response.content)
                if progress_callback:
                    progress_callback(len(response.content), len(response.content))

                # Verify it's actually a PDF
                with open(temp_path, "rb") as f:
                    header = f.read(4)
                    if header != b"%PDF":
                        os.unlink(temp_path)
                        return False, "Downloaded file is not a valid PDF"

                # Move to final destination
                shutil.move(temp_path, output_path)
                logger.debug(f"[curl_cffi] Successfully downloaded {len(response.content)} bytes")
                return True, None

            except Exception:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

        except Exception as e:
            logger.debug(f"[curl_cffi] Download failed: {e}")
            return False, str(e)

    def get_page_content(
        self,
        url: str,
        *,
        timeout_seconds: float | None = None,
        force_challenge_bypass: bool = False,
    ) -> tuple[str | None, int | None]:
        """
        Get HTML content from a URL with automatic curl_cffi fallback on 403.

        Returns:
            Tuple of (html_content, status_code)
        """
        try:
            request_timeout = float(self.timeout)
            if timeout_seconds is not None:
                request_timeout = max(1.0, float(timeout_seconds))
            response = self.session.get(url, timeout=request_timeout)
            self._emit_html_snapshot(
                url=url,
                status_code=response.status_code,
                html=response.text,
                fetcher="requests",
            )

            # If we get 403, try curl_cffi bypass
            if response.status_code == 403:
                if is_akamai_access_denied_html(response.text):
                    logger.info(
                        "Detected Akamai access-denied hard block; skipping page bypass attempts"
                    )
                    return response.text, response.status_code
                if self.fast_fail and not force_challenge_bypass:
                    if not self._should_attempt_fast_fail_page_bypass(url, response.text):
                        logger.info("Fast-fail enabled: skipping 403 bypass for page access")
                        return response.text, response.status_code
                    logger.info(
                        "Fast-fail enabled: trying single curl_cffi page bypass for recoverable host"
                    )
                    html, status = self._get_page_with_curl_cffi(
                        url, timeout_seconds=request_timeout
                    )
                    if html:
                        logger.info("Successfully fetched page using curl_cffi bypass")
                        return html, status
                    logger.warning("curl_cffi bypass failed for fast-fail page access")
                    return response.text, response.status_code
                logger.warning("Got 403 accessing page, attempting cloudscraper bypass...")
                html, status = self._get_page_with_cloudscraper(
                    url, timeout_seconds=request_timeout
                )
                if html:
                    logger.info("Successfully fetched page using cloudscraper bypass")
                    return html, status
                logger.warning("cloudscraper bypass also failed for page access")

                logger.warning("Got 403 accessing page, attempting curl_cffi bypass...")
                html, status = self._get_page_with_curl_cffi(url, timeout_seconds=request_timeout)
                if html:
                    logger.info("Successfully fetched page using curl_cffi bypass")
                    return html, status
                logger.warning("curl_cffi bypass also failed for page access")

            return response.text, response.status_code
        except Exception as e:
            logger.error(f"Error fetching page content: {e}")
            self._emit_html_snapshot(
                url=url,
                status_code=None,
                html=None,
                fetcher="requests",
                error=str(e),
            )
            return None, None

    def _new_download_deadline(self) -> float | None:
        if self.download_deadline_seconds is None:
            return None
        return time.monotonic() + self.download_deadline_seconds

    def _effective_timeout(self, deadline_ts: float | None) -> float:
        if deadline_ts is None:
            return float(self.timeout)
        remaining = deadline_ts - time.monotonic()
        return max(1.0, min(float(self.timeout), remaining))

    def _check_deadline(self, deadline_ts: float | None) -> None:
        if deadline_ts is None:
            return
        if time.monotonic() <= deadline_ts:
            return
        limit = self.download_deadline_seconds
        if limit is None:
            raise RetryableError("Download deadline exceeded")
        raise RetryableError(f"Download deadline exceeded ({limit:.1f}s)")

    def _can_extend_deadline_for_active_fast_fail_download(
        self,
        *,
        url: str,
        bytes_downloaded: int,
        extensions_used: int,
    ) -> bool:
        if not self.fast_fail:
            return False
        if (
            self.download_deadline_seconds is None
            or self.download_deadline_seconds < self._FAST_FAIL_DEADLINE_MIN_SECONDS_FOR_GRACE
        ):
            return False
        if extensions_used >= self._FAST_FAIL_DEADLINE_MAX_EXTENSIONS:
            return False
        if bytes_downloaded < self._FAST_FAIL_DEADLINE_PROGRESS_MIN_BYTES:
            return False

        parsed = urlparse((url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        host = parsed.netloc.lower()
        if self._is_obvious_non_academic_host(host):
            return False
        path = (parsed.path or "").lower()
        query = (parsed.query or "").lower()
        return looks_like_pdf_download_path(path=path, query=query)

    @classmethod
    def _is_obvious_non_academic_host(cls, host: str) -> bool:
        if not host:
            return False
        if host.endswith(".edu") or host.endswith(".gov") or ".ac." in host:
            return False
        if any(marker in host for marker in cls._ACADEMIC_HOST_MARKERS):
            return False
        return any(marker in host for marker in cls._NON_ACADEMIC_HOST_MARKERS)

    def _should_fast_fail_non_academic_url(self, url: str) -> bool:
        if not self.fast_fail:
            return False
        parsed = urlparse((url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        host = parsed.netloc.lower()
        return self._is_obvious_non_academic_host(host)

    def _should_fast_fail_skip_challenge_pdf_url(self, url: str) -> bool:
        if not self.fast_fail:
            return False
        parsed = urlparse((url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        host = parsed.netloc.lower()
        if not any(marker in host for marker in self._FAST_FAIL_SKIP_CHALLENGE_DOWNLOAD_HOSTS):
            return False
        path = (parsed.path or "").lower()
        query = (parsed.query or "").lower()
        return path.endswith(".pdf") or ".pdf" in query or "/pdf" in path or "pdfft" in path

    def _get_page_with_cloudscraper(
        self,
        url: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str | None, int | None]:
        """
        Fetch page content using cloudscraper to solve JS challenges.

        Args:
            url: URL to fetch

        Returns:
            Tuple of (html_content, status_code)
        """
        try:
            import cloudscraper
        except ImportError:
            return None, None

        try:
            scraper = cloudscraper.create_scraper()
            request_timeout = float(self.timeout)
            if timeout_seconds is not None:
                request_timeout = max(1.0, float(timeout_seconds))
            response = scraper.get(url, timeout=request_timeout)
            logger.debug(f"[cloudscraper] Page fetch status: {response.status_code}")
            self._emit_html_snapshot(
                url=url,
                status_code=response.status_code,
                html=response.text,
                fetcher="cloudscraper",
            )
            return response.text, response.status_code
        except Exception as e:
            logger.debug(f"[cloudscraper] Page fetch failed: {e}")
            self._emit_html_snapshot(
                url=url,
                status_code=None,
                html=None,
                fetcher="cloudscraper",
                error=str(e),
            )
            return None, None

    def _get_page_with_curl_cffi(
        self,
        url: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str | None, int | None]:
        """
        Fetch page content using curl_cffi with browser impersonation.

        Args:
            url: URL to fetch

        Returns:
            Tuple of (html_content, status_code)
        """
        try:
            from curl_cffi import requests as cf_requests
        except ImportError:
            return None, None

        import time
        from urllib.parse import urlparse

        try:
            # Extract domain for rate limiting
            domain = urlparse(url).netloc

            # Rate limiting: wait if we recently made a request to this domain
            if domain in self._last_bypass_time:
                elapsed = time.time() - self._last_bypass_time[domain]
                if elapsed < self._bypass_delay:
                    wait_time = self._bypass_delay - elapsed
                    logger.info(f"[curl_cffi] Rate limiting: waiting {wait_time:.1f}s for {domain}")
                    time.sleep(wait_time)

            # Use Chrome 110 impersonation
            logger.debug(f"[curl_cffi] Fetching page with Chrome 110 impersonation: {url}")
            request_timeout = float(self.timeout)
            if timeout_seconds is not None:
                request_timeout = max(1.0, float(timeout_seconds))
            response = cf_requests.get(
                url,
                impersonate="chrome110",
                timeout=request_timeout,
                headers={"Referer": url},
            )

            # Update last request time for this domain
            self._last_bypass_time[domain] = time.time()

            logger.debug(f"[curl_cffi] Page fetch status: {response.status_code}")
            self._emit_html_snapshot(
                url=url,
                status_code=response.status_code,
                html=response.text,
                fetcher="curl_cffi",
            )
            return response.text, response.status_code

        except Exception as e:
            logger.debug(f"[curl_cffi] Page fetch failed: {e}")
            self._emit_html_snapshot(
                url=url,
                status_code=None,
                html=None,
                fetcher="curl_cffi",
                error=str(e),
            )
            return None, None

    def _prefetch_landing_page(
        self,
        *,
        landing_url: str,
        request_timeout: float,
    ) -> None:
        if not self._should_prefetch_landing_host(landing_url):
            return
        try:
            self.session.get(landing_url, timeout=request_timeout)
        except Exception:
            return

    def _prefetch_landing_page_curl_cffi(
        self,
        *,
        session: Any,
        landing_url: str,
    ) -> None:
        if not self._should_prefetch_landing_host(landing_url):
            return
        try:
            session.get(
                landing_url,
                impersonate="chrome110",
                timeout=min(self.timeout, 8),
                headers={"Referer": landing_url},
            )
        except Exception:
            return

    def _should_prefetch_landing_host(self, landing_url: str) -> bool:
        parsed = urlparse((landing_url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        hosts = getattr(self._prefetch_cache_local, "hosts", None)
        if hosts is None:
            hosts = set()
            self._prefetch_cache_local.hosts = hosts
        host = parsed.netloc.lower()
        if host in hosts:
            return False
        hosts.add(host)
        return True

    def _should_attempt_fast_fail_page_bypass(self, url: str, html: str) -> bool:
        parsed = urlparse((url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        host = parsed.netloc.lower()
        is_scihub = any(marker in host for marker in self._FAST_FAIL_PAGE_BYPASS_SCIHUB_MARKERS)
        if any(marker in host for marker in self._FAST_FAIL_SKIP_PAGE_BYPASS_HOSTS):
            return False
        if not is_scihub and not any(marker in host for marker in self._FAST_FAIL_PAGE_BYPASS_HOSTS):
            return False
        if is_hard_challenge_block_html(html) and not is_scihub:
            return False
        if is_auth_or_paywall_html(html):
            return False
        if is_challenge_html(html):
            return True
        return is_scihub and is_hard_challenge_block_html(html)
