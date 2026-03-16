"""
OSTI (Office of Scientific and Technical Information) source implementation.

Handles DOE technical report DOIs under the 10.2172 prefix.
"""

from __future__ import annotations

import re

from ..utils.logging import get_logger
from .base import PaperSource

logger = get_logger(__name__)


class OSTISource(PaperSource):
    """Resolve 10.2172 DOIs to OSTI PDF endpoints."""

    _OSTI_DOI_RE = re.compile(r"(?:^|\b)10\.2172/(?P<id>\d+)(?:\b|$)", re.IGNORECASE)

    @property
    def name(self) -> str:
        return "OSTI"

    def can_handle(self, identifier: str) -> bool:
        return self._extract_osti_id(identifier) is not None

    def get_pdf_url(self, identifier: str) -> str | None:
        osti_id = self._extract_osti_id(identifier)
        if not osti_id:
            return None
        pdf_url = f"https://www.osti.gov/servlets/purl/{osti_id}"
        logger.info(f"[OSTI] Using direct PDF endpoint: {pdf_url}")
        return pdf_url

    @classmethod
    def _extract_osti_id(cls, identifier: str) -> str | None:
        match = cls._OSTI_DOI_RE.search((identifier or "").strip())
        if not match:
            return None
        return match.group("id")
