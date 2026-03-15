"""
Generic HTML landing page source implementation.

This source tries to extract a direct PDF link from an article landing page.
It is primarily intended for open-access repository/journal pages where the PDF
URL is discoverable in the HTML (e.g. citation meta tags or download links).
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse, urlunparse

from ..core.downloader import FileDownloader
from ..core.pdf_link_extractor import derive_publisher_pdf_candidates, extract_ranked_pdf_candidates
from ..utils.logging import get_logger
from .base import PaperSource

logger = get_logger(__name__)


class HTMLLandingSource(PaperSource):
    """Extract PDF URLs from generic HTML pages."""

    _MIN_CANDIDATE_SCORE = 500
    _MAX_PROBE_CANDIDATES = 3
    _FAST_FAIL_SKIP_HTML_HOST_MARKERS = (
        "researchgate.net",
        "academia.edu",
        "sk.sagepub.com",
        "ideas.repec.org",
        "scispace.com",
        "sciencedirect.com",
    )
    _FAST_FAIL_FORCE_PAGE_BYPASS_HOST_MARKERS = (
        "mdpi.com",
        "doi.org",
        "journals.sagepub.com",
        "papers.ssrn.com",
        "onlinelibrary.wiley.com",
        "asmedigitalcollection.asme.org",
        "durham-repository.worktribe.com",
    )
    _FAST_FAIL_DIRECT_PREFETCH_HOST_MARKERS = (
        "mdpi.com",
        "nature.com",
        "tandfonline.com",
    )
    _FAST_FAIL_READER_FALLBACK_HOST_MARKERS = (
        "mdpi.com",
        "doi.org",
        "dx.doi.org",
        "journals.sagepub.com",
        "papers.ssrn.com",
        "onlinelibrary.wiley.com",
        "asmedigitalcollection.asme.org",
        "durham-repository.worktribe.com",
        "nature.com",
        "link.springer.com",
    )
    _FAST_FAIL_ACADEMIC_HINTS = (
        "journal",
        "research",
        "scholar",
        "library",
        "archive",
        "repository",
        "university",
        "institute",
    )
    _ACADEMIC_HOST_MARKERS = (
        "arxiv.org",
        "ncbi.nlm.nih.gov",
        "pmc.ncbi.nlm.nih.gov",
        "sciencedirect.com",
        "springer.com",
        "nature.com",
        "wiley.com",
        "onlinelibrary.wiley.com",
        "tandfonline.com",
        "sagepub.com",
        "mdpi.com",
        "ieeexplore.ieee.org",
        "acm.org",
        "jstor.org",
        "scielo.org",
        "researchgate.net",
        "semanticscholar.org",
        "doaj.org",
        "hindawi.com",
        "frontiersin.org",
        "doi.org",
        "dx.doi.org",
        "ieee.org",
        "sdewes.org",
        "ideas.repec.org",
        "asme.org",
        "intechopen.com",
        "dergipark.org.tr",
        "iaea.org",
        "ugent.be",
        "ceon.rs",
        "scirp.org",
        "ssrn.com",
    )
    _NON_ACADEMIC_HOST_MARKERS = (
        "tiktok.com",
        "instagram.com",
        "facebook.com",
        "x.com",
        "twitter.com",
        "youtube.com",
        "youtu.be",
        "reddit.com",
        "bbc.com",
        "cnn.com",
        "abcnews.com",
        "consumerreports.org",
        "creativebloq.com",
        "medium.com",
        "luxuryestate.com",
        "campaignlive.com",
        "campaignasia.com",
        "healthline.com",
        "hbr.org",
        "carscoops.com",
        "thisismoney.co.uk",
        "topgear.com",
        "tesla.com",
        "jaguar.com",
        "wikipedia.org",
        "sky.com",
        "investors.com",
        "businessinsider.com",
        "bloomberg.com",
        "cnbc.com",
        "fortune.com",
        "britannica.com",
        "merriam-webster.com",
        "finance.yahoo.com",
        "motortrend.com",
        "creativeboom.com",
        "365dm.com",
        "x666.me",
        "brandvm.com",
        "cdotimes.com",
        "nikkeibizruptors.com",
        "globalspec.com",
        "yahoo.com",
        "imgix.net",
        "academia-photos.com",
        "jlaforums.com",
        "avanzaagency.com",
        "thesiliconreview.com",
        "mediawatcher.ai",
        "nielseniq.com",
        "autocar.co.uk",
        "forbes.com",
        "reuters.com",
        "euronews.com",
        "slidesharecdn.com",
    )
    _FAST_FAIL_NON_PAPER_PATH_RULES: tuple[tuple[str, str], ...] = (
        ("scholar.google.com", "/scholar"),
        ("link.springer.com", "/subjects/"),
        ("nature.com", "/collections/"),
        ("springernature.com", "/gp/librarians/"),
        ("blog.bham.ac.uk", "/socialsciencesbirmingham/"),
        ("tgmresearch.com", "/consumer-insights-guide/"),
        ("snap.berkeley.edu", "/project/"),
        ("jlaforums.com", "/viewforum.php"),
        ("jlaforums.com", "/viewrecent.php"),
        ("jlaforums.com", "/album.php"),
        ("jlaforums.com", "/rss.php"),
        ("ieee.org", "/profile/"),
        ("sdewes.org", "/membership.php"),
        ("sdewes.org", "/isc.php"),
        ("doi.org", "/["),
        ("dx.doi.org", "/["),
        ("mdpi.com", "/about"),
        ("mdpi.com", "/topics"),
        ("mdpi.com", "/authors"),
        ("mdpi.com", "/editors"),
        ("mdpi.com", "/reviewers"),
        ("mdpi.com", "/journal"),
        ("mdpi.com", "/special_issues"),
        ("mdpi.com", "/redirect/new_site"),
        ("ieeexplore.ieee.org", "/author/"),
        ("ieeexplore.ieee.org", "/browse/"),
        ("ieeexplore.ieee.org", "/xpl/conhome/"),
        ("ieeexplore.ieee.org", "/xplore/home.jsp"),
    )

    def __init__(self, downloader: FileDownloader):
        self.downloader = downloader

    @property
    def name(self) -> str:
        return "HTML Landing"

    def can_handle(self, identifier: str) -> bool:
        cleaned = self._normalize_landing_url(identifier)
        cleaned = self._strip_fragment(cleaned)
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False

        # If the URL already looks like a direct PDF, let DirectPDFSource handle it first.
        if parsed.path.lower().endswith(".pdf"):
            return False

        host = parsed.netloc.lower()
        path = (parsed.path or "").lower()
        fast_fail = bool(getattr(self.downloader, "fast_fail", False))
        if fast_fail and not self._is_likely_academic_host(host):
            logger.debug(f"[HTML Landing] Fast-fail skip for non-academic host: {host}")
            return False
        if fast_fail and self._is_fast_fail_non_paper_path(host, path):
            logger.debug(f"[HTML Landing] Fast-fail skip for non-paper path: {host}{path}")
            return False

        if self._is_obvious_non_academic_host(host):
            logger.debug(f"[HTML Landing] Skipping obvious non-academic host: {host}")
            return False

        return True

    def get_pdf_url(self, identifier: str) -> str | None:
        if not self.can_handle(identifier):
            return None

        base_url = self._normalize_landing_url(identifier)
        base_url = self._strip_fragment(base_url)
        host = urlparse(base_url).netloc.lower()
        fast_fail = bool(getattr(self.downloader, "fast_fail", False))
        skip_html_fetch = fast_fail and self._should_skip_html_fetch(host)

        # Try deterministic publisher URL derivation before full-page fetch.
        prefetch_candidates = derive_publisher_pdf_candidates(base_url)
        prefetch_candidates = [
            url
            for url in prefetch_candidates
            if not self._is_unhelpful_candidate_url(url)
            and not self._is_malformed_candidate_url(url)
        ]
        if self._should_accept_single_prefetch_candidate_without_probe(
            host=host,
            fast_fail=fast_fail,
            candidates=prefetch_candidates,
        ):
            selected = prefetch_candidates[0]
            logger.info(f"[HTML Landing] Using deterministic prefetch candidate: {selected}")
            return selected
        prefetched = self._probe_candidates(prefetch_candidates, mode="prefetch")
        if prefetched:
            return prefetched
        if skip_html_fetch:
            logger.debug(
                f"[HTML Landing] Fast-fail skip challenge-heavy host before full-page fetch: {host}"
            )
            return None

        force_challenge_bypass = fast_fail and any(
            marker in host for marker in self._FAST_FAIL_FORCE_PAGE_BYPASS_HOST_MARKERS
        )
        html, status = self._fetch_page_content(
            base_url, force_challenge_bypass=force_challenge_bypass
        )
        if not html:
            return None
        if fast_fail and self._looks_like_challenge_html(html):
            logger.debug("[HTML Landing] Fast-fail: challenge HTML detected, skipping extraction")
            return None

        if self._should_force_reader_before_extraction(
            host=host,
            status=status,
            html=html,
            fast_fail=fast_fail,
        ):
            reader_html, reader_status = self._fetch_page_with_jina_reader(base_url)
            if reader_html:
                html, status = reader_html, reader_status

        # Sometimes a server returns a PDF even for a non-.pdf URL.
        if status == 200 and html.lstrip().startswith("%PDF"):
            logger.debug("[HTML Landing] Page content appears to be a PDF; using original URL")
            return base_url

        candidates = self._extract_candidates_from_html(html=html, base_url=base_url)

        # Optional probe to avoid selecting tracker/challenge endpoints when multiple
        # candidates are present.
        probed = self._probe_candidates(candidates, mode="html")
        if probed:
            return probed

        # Reader fallback is expensive; only attempt when primary HTML did not yield
        # a usable candidate.
        if self._should_try_reader_fallback(
            host=host,
            status=status,
            html=html,
            fast_fail=fast_fail,
        ):
            reader_html, reader_status = self._fetch_page_with_jina_reader(base_url)
            if reader_html:
                reader_candidates = self._extract_candidates_from_html(
                    html=reader_html,
                    base_url=base_url,
                )
                reader_probed = self._probe_candidates(reader_candidates, mode="reader")
                if reader_probed:
                    return reader_probed
                html, status = reader_html, reader_status
                candidates = reader_candidates

        if not candidates:
            return None

        if status != 200:
            logger.debug(
                f"[HTML Landing] Non-200 page ({status}) did not yield a valid PDF candidate"
            )
            return None

        # In fast-fail mode, do not trust unprobed candidates. This avoids expensive
        # dead-end downloads (e.g., login/challenge endpoints masquerading as PDFs).
        if fast_fail:
            logger.debug("[HTML Landing] Fast-fail: rejecting unprobed PDF candidate(s)")
            return None

        best = candidates[0]
        logger.info(f"[HTML Landing] Extracted PDF URL: {best}")
        return best

    def _extract_candidates_from_html(self, *, html: str, base_url: str) -> list[str]:
        ranked_candidates = extract_ranked_pdf_candidates(html, base_url)
        candidates = [url for score, url in ranked_candidates if score >= self._MIN_CANDIDATE_SCORE]
        candidates = [
            url
            for url in candidates
            if not self._is_unhelpful_candidate_url(url)
            and not self._is_malformed_candidate_url(url)
        ]
        if not candidates:
            logger.debug(
                "[HTML Landing] No high-confidence PDF candidates found "
                f"(threshold={self._MIN_CANDIDATE_SCORE})"
            )
        return candidates

    @staticmethod
    def _strip_fragment(url: str) -> str:
        parsed = urlparse(url)
        if not parsed.fragment:
            return url
        return urlunparse(parsed._replace(fragment=""))

    @classmethod
    def _normalize_landing_url(cls, url: str) -> str:
        parsed = urlparse((url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return url
        host = parsed.netloc.lower()
        path = parsed.path or ""

        if "mdpi.com" in host and path.rstrip("/") == "/redirect/new_site":
            return_values = parse_qs(parsed.query).get("return") or []
            if return_values:
                return_value = (return_values[0] or "").strip()
                if return_value.startswith("/"):
                    normalized = parsed._replace(
                        netloc="www.mdpi.com", path=return_value, query="", fragment=""
                    )
                    return urlunparse(normalized)
        return url

    @classmethod
    def _is_obvious_non_academic_host(cls, host: str) -> bool:
        if not host:
            return False

        if host.endswith(".edu") or host.endswith(".gov") or ".ac." in host:
            return False

        if any(marker in host for marker in cls._ACADEMIC_HOST_MARKERS):
            return False

        return any(marker in host for marker in cls._NON_ACADEMIC_HOST_MARKERS)

    @classmethod
    def _is_likely_academic_host(cls, host: str) -> bool:
        if not host:
            return False
        if host.endswith(".edu") or host.endswith(".gov") or ".ac." in host:
            return True
        if any(marker in host for marker in cls._ACADEMIC_HOST_MARKERS):
            return True
        return any(hint in host for hint in cls._FAST_FAIL_ACADEMIC_HINTS)

    def _probe_candidates(self, candidates: list[str], *, mode: str) -> str | None:
        if not candidates:
            return None
        probe_pdf_url = getattr(self.downloader, "probe_pdf_url", None)
        if not callable(probe_pdf_url):
            return candidates[0]
        for candidate in candidates[: self._MAX_PROBE_CANDIDATES]:
            try:
                if probe_pdf_url(candidate):
                    logger.info(f"[HTML Landing] Extracted PDF URL ({mode} probed): {candidate}")
                    return candidate
            except Exception as e:
                logger.debug(f"[HTML Landing] Probe failed for {candidate}: {e}")
        return None

    def _fetch_page_content(
        self, url: str, *, force_challenge_bypass: bool
    ) -> tuple[str | None, int | None]:
        fetcher = self.downloader.get_page_content
        if force_challenge_bypass:
            try:
                return fetcher(url, force_challenge_bypass=True)
            except TypeError:
                logger.debug(
                    "[HTML Landing] Downloader does not support force_challenge_bypass kwarg"
                )
        return fetcher(url)

    def _fetch_page_with_jina_reader(self, url: str) -> tuple[str | None, int | None]:
        reader_url = self._build_jina_reader_url(url)
        if not reader_url:
            return None, None
        logger.debug(f"[HTML Landing] Trying jina reader fallback: {reader_url}")
        fetcher = self.downloader.get_page_content
        try:
            return fetcher(reader_url, timeout_seconds=3.0)
        except TypeError:
            return fetcher(reader_url)

    @staticmethod
    def _build_jina_reader_url(url: str) -> str | None:
        parsed = urlparse((url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        if "r.jina.ai" in parsed.netloc.lower():
            return None
        suffix = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            suffix = f"{suffix}?{parsed.query}"
        return f"https://r.jina.ai/{suffix}"

    @classmethod
    def _should_try_reader_fallback(
        cls,
        *,
        host: str,
        status: int | None,
        html: str | None,
        fast_fail: bool,
    ) -> bool:
        if not fast_fail:
            return False
        if not any(marker in host for marker in cls._FAST_FAIL_READER_FALLBACK_HOST_MARKERS):
            return False
        lowered_html = (html or "").lower()
        if status == 403 and "mdpi.com" in host and "access denied" in lowered_html:
            return True
        challenge_like = cls._looks_like_challenge_html(html)
        if status in {403, 429, 451, 503, 520, 521, 522, 523, 524}:
            return challenge_like
        return status == 200 and challenge_like

    @staticmethod
    def _should_force_reader_before_extraction(
        *, host: str, status: int | None, html: str | None, fast_fail: bool
    ) -> bool:
        if not fast_fail:
            return False
        if "mdpi.com" not in host:
            return False
        if status != 403:
            return False
        lowered = (html or "").lower()
        return "access denied" in lowered and "errors.edgesuite.net" in lowered

    @classmethod
    def _looks_like_challenge_html(cls, html: str | None) -> bool:
        lowered = (html or "").lower()
        return any(
            token in lowered
            for token in (
                "just a moment...",
                "window._cf_chl_opt",
                "/cdn-cgi/challenge-platform/",
                "__cf_chl",
                "captcha.awswaf.com",
                "verify that you're not a robot",
                "access denied",
                "errors.edgesuite.net",
            )
        )

    @classmethod
    def _should_accept_single_prefetch_candidate_without_probe(
        cls, *, host: str, fast_fail: bool, candidates: list[str]
    ) -> bool:
        if not fast_fail or len(candidates) != 1:
            return False
        if not any(marker in host for marker in cls._FAST_FAIL_DIRECT_PREFETCH_HOST_MARKERS):
            return False
        candidate = (candidates[0] or "").lower()
        if cls._is_unhelpful_candidate_url(candidate) or cls._is_malformed_candidate_url(candidate):
            return False
        return ".pdf" in candidate or "/pdf" in candidate

    @classmethod
    def _should_skip_html_fetch(cls, host: str) -> bool:
        return any(marker in host for marker in cls._FAST_FAIL_SKIP_HTML_HOST_MARKERS)

    @classmethod
    def _is_fast_fail_non_paper_path(cls, host: str, path: str) -> bool:
        if not host:
            return False
        if "ieeexplore.ieee.org" in host and (
            path.endswith("/metrics")
            or path.endswith("/references")
            or path.endswith("/similar")
            or path.endswith("/citations")
        ):
            return True
        for host_marker, path_prefix in cls._FAST_FAIL_NON_PAPER_PATH_RULES:
            if host_marker in host and path.startswith(path_prefix):
                return True
        return False

    @staticmethod
    def _is_unhelpful_candidate_url(url: str) -> bool:
        lowered = (url or "").lower()
        parsed = urlparse(lowered)
        host = parsed.netloc
        path = parsed.path
        if "ieeexplore.ieee.org" in host and (
            "/metrics" in path
            or "/references" in path
            or "/similar" in path
            or "/citations" in path
            or path.startswith("/document/")
        ):
            return True
        return any(
            token in lowered
            for token in (
                "/login",
                "/signin",
                "/redirect/new_site/pdf",
                "/user/manuscripts/upload/pdf",
                "/user/login/pdf",
                "/subscribe",
                "/purchase",
                "/cart",
                "openathens",
                "shibboleth",
                "__cf_chl",
                "/cdn-cgi/challenge-platform/",
            )
        )

    @staticmethod
    def _is_malformed_candidate_url(url: str) -> bool:
        lowered = (url or "").lower()
        if not lowered:
            return True
        if any(token in lowered for token in ("](", ")[", "{", "}")):
            return True
        if "http://" in lowered[8:] or "https://" in lowered[8:]:
            return True
        return any(token in lowered for token in (">m_auth=", ">m_preview=", ">m_id=", ")]("))
