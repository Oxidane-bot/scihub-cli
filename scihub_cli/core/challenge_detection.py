"""
HTML challenge and block-page detection utilities.

Pure functions with no external state dependencies.
"""

import re
from urllib.parse import parse_qs, urlparse, urlunparse


def is_hard_challenge_block_html(html: str) -> bool:
    lowered = (html or "").lower()
    return any(
        token in lowered
        for token in (
            "attention required! | cloudflare",
            "cloudflare ray id",
            "cf-error-details",
            "captcha.awswaf.com",
            "captchascript.rendercaptcha",
            "verify that you're not a robot",
            "recaptcha/api.js",
            "grecaptcha.render",
        )
    )


def is_akamai_access_denied_html(html: str) -> bool:
    lowered = (html or "").lower()
    return (
        "access denied" in lowered
        and "errors.edgesuite.net" in lowered
        and "don't have permission to access" in lowered
    )


def is_challenge_html(html: str) -> bool:
    lowered = (html or "").lower()
    return any(
        token in lowered
        for token in (
            "just a moment...",
            "enable javascript and cookies to continue",
            "window._cf_chl_opt",
            "/cdn-cgi/challenge-platform/",
            "__cf_chl",
        )
    )


def is_auth_or_paywall_html(html: str) -> bool:
    lowered = (html or "").lower()
    return any(
        token in lowered
        for token in (
            "sign up or log in to continue reading",
            "institutional login",
            "institutional access",
            "openathens",
            "shibboleth",
            "subscribe",
            "subscription",
            "purchase this article",
            "buy article",
            "rent this article",
            "get access",
            "paywall",
            "open-login-modal",
            "download free pdf",
            "subscribers only",
            "ieee xplore login",
            "currentpage:  'login'",
            "apm_do_not_touch",
            "/tspd/",
            "osano-cookie-consent-xplore",
            "recaptcha",
            "purchase",
            "buy this article",
        )
    )


def should_fast_fail_probe_403_html(html: str) -> bool:
    return (
        is_hard_challenge_block_html(html)
        or is_challenge_html(html)
        or is_auth_or_paywall_html(html)
    )


def looks_like_pdf_download_path(*, path: str, query: str) -> bool:
    return (
        path.endswith(".pdf")
        or ".pdf" in path
        or ".pdf" in query
        or "/pdf" in path
        or "/download/" in path
        or "/bitstream/" in path
        or "/server/api/core/bitstreams/" in path
    )


def normalize_download_url(url: str) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        return cleaned
    if cleaned.endswith("?"):
        cleaned = cleaned[:-1]

    try:
        parsed = urlparse(cleaned)
    except ValueError:
        return cleaned
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return cleaned

    host = parsed.netloc.lower()
    path = parsed.path or ""
    query = parsed.query or ""

    if parsed.scheme == "http" and any(
        marker in host
        for marker in (
            "mdpi.com",
            "mdpi-res.com",
            "res.mdpi.com",
            "ieeexplore.ieee.org",
        )
    ):
        parsed = parsed._replace(scheme="https")

    if (
        "mdpi.com" in host or "mdpi-res.com" in host or "res.mdpi.com" in host
    ) and path.lower().endswith("/pdf") and not query:
        parsed = parsed._replace(query="download=1")

    return urlunparse(parsed)


def normalize_recovery_url(url: str) -> str | None:
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    cleaned_path = re.sub(r"(\.pdf)+$", ".pdf", parsed.path or "", flags=re.I)
    if cleaned_path:
        lower = cleaned_path.lower()
        idx = lower.find(".pdf")
        if idx != -1:
            cleaned_path = cleaned_path[: idx + 4]
    return urlunparse(parsed._replace(path=cleaned_path, fragment=""))


def is_scihub_host(url: str) -> bool:
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    host = parsed.netloc.lower()
    return "sci-hub" in host


def derive_alternate_pdf_urls(url: str) -> list[str]:
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return []
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return []
    host = parsed.netloc.lower()
    path = parsed.path or ""
    lowered_path = path.lower()
    query_params = parse_qs(parsed.query or "")

    out: list[str] = []

    if (
        "/server/api/core/bitstreams/" in lowered_path or "/bitstreams/" in lowered_path
    ) and "/content" not in lowered_path:
        out.append(urlunparse(parsed._replace(path=path.rstrip("/") + "/content", query="")))

    if "onlinelibrary.wiley.com" in host:
        if any(token in lowered_path for token in ("/doi/pdf", "/doi/epdf", "/doi/pdfdirect")):
            return []
        match = re.search(r"/doi/(?:pdfdirect|pdf|epdf|abs|full)/(.+)", path, re.I)
        if match:
            doi = match.group(1).strip().strip("/")
            if doi and doi.startswith("10.") and "/" in doi:
                out.extend(
                    [
                        f"https://onlinelibrary.wiley.com/doi/epdf/{doi}",
                        f"https://onlinelibrary.wiley.com/doi/pdf/{doi}",
                        f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}",
                    ]
                )
        match = re.search(r"/doi/(10\\.[^/]+/[^/?#]+)(?:/|$)", path, re.I)
        if match:
            doi = match.group(1).strip().strip("/")
            if doi and "/" in doi:
                out.extend(
                    [
                        f"https://onlinelibrary.wiley.com/doi/epdf/{doi}",
                        f"https://onlinelibrary.wiley.com/doi/pdf/{doi}",
                        f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}",
                    ]
                )

    if "tandfonline.com" in host:
        if any(token in lowered_path for token in ("/doi/pdf", "/doi/epdf")):
            return []
        match = re.search(r"/doi/(?:abs|full|pdf)/(.+)", path, re.I)
        if match:
            doi = match.group(1).strip().strip("/")
            if doi and doi.startswith("10.") and "/" in doi:
                out.append(f"https://www.tandfonline.com/doi/pdf/{doi}?download=true")
        match = re.search(r"/doi/(10\\.[^/]+/[^/?#]+)(?:/|$)", path, re.I)
        if match:
            doi = match.group(1).strip().strip("/")
            if doi and "/" in doi:
                out.append(f"https://www.tandfonline.com/doi/pdf/{doi}?download=true")

    if "papers.ssrn.com" in host and "/sol3/delivery.cfm" in lowered_path:
        abstract_id = (
            (query_params.get("abstractid") or query_params.get("abstract_id") or [None])[0]
        )
        if abstract_id:
            base = f"https://papers.ssrn.com/sol3/Delivery.cfm?abstractid={abstract_id}"
            out.extend(
                [
                    base,
                    f"{base}&type=2",
                    f"{base}&download=1",
                ]
            )

    if "ncbi.nlm.nih.gov" in host or "pmc.ncbi.nlm.nih.gov" in host:
        match = re.search(r"/pmc/articles/(pmc\\d+)", lowered_path)
        if match:
            pmc_id = match.group(1).upper()
            out.append(
                f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmc_id}&blobtype=pdf"
            )

    if "europepmc.org" in host and "/articles/pmc" in lowered_path:
        match = re.search(r"/articles/(pmc\\d+)", lowered_path)
        if match:
            pmc_id = match.group(1).upper()
            out.append(
                f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmc_id}&blobtype=pdf"
            )

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for candidate in out:
        if candidate == url or candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def derive_landing_prefetch_url(url: str) -> str | None:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    host = parsed.netloc.lower()
    path = parsed.path or ""
    query = parse_qs(parsed.query or "")

    if "mdpi.com" in host and "/pdf" in path:
        landing_path = path.replace("/pdf", "")
        return urlunparse(parsed._replace(path=landing_path, query=""))

    if "sciencedirect.com" in host:
        pii_match = re.search(r"/pii/([A-Z0-9]+)", path, flags=re.I)
        if pii_match:
            pii = pii_match.group(1)
            landing_path = f"/science/article/pii/{pii}"
            return urlunparse(
                parsed._replace(netloc="www.sciencedirect.com", path=landing_path, query="")
            )

    if "onlinelibrary.wiley.com" in host and (
        path.startswith("/doi/pdfdirect/") or path.startswith("/doi/pdf/")
    ):
        doi = path.split("/doi/", 1)[1].replace("pdfdirect/", "").replace("pdf/", "")
        return urlunparse(parsed._replace(path=f"/doi/full/{doi}", query=""))

    if "academic.oup.com" in host and (
        "/article-pdf/doi/" in path or "/advance-article-pdf/doi/" in path
    ):
        parts = path.split("/doi/", 1)
        if len(parts) == 2:
            doi = parts[1].split("/", 1)[0]
            return urlunparse(parsed._replace(path=f"/doi/{doi}", query=""))

    if "papers.ssrn.com" in host:
        abstract_id = (query.get("abstractid") or query.get("abstract_id") or [None])[0]
        if abstract_id:
            landing_path = "/sol3/papers.cfm"
            landing_query = f"abstract_id={abstract_id}"
            return urlunparse(parsed._replace(path=landing_path, query=landing_query))

    if "tandfonline.com" in host and "/doi/pdf/" in path:
        doi = path.split("/doi/pdf/", 1)[1]
        return urlunparse(parsed._replace(path=f"/doi/full/{doi}", query=""))

    return None
