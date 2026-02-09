"""
Main Sci-Hub client providing high-level interface with multi-source support.
"""

import os
import time
from typing import Optional

from .config.settings import settings
from .converters.pdf_to_md import PdfToMarkdownConverter
from .core.doi_processor import DOIProcessor
from .core.downloader import FileDownloader
from .core.file_manager import FileManager
from .core.mirror_manager import MirrorManager
from .core.parser import ContentParser
from .core.source_manager import SourceManager
from .models import DownloadProgress, DownloadResult, ProgressCallback
from .network.session import BasicSession
from .sources.arxiv_source import ArxivSource
from .sources.core_source import CORESource
from .sources.direct_pdf_source import DirectPDFSource
from .sources.html_landing_source import HTMLLandingSource
from .sources.pmc_source import PMCSource
from .sources.scihub_source import SciHubSource
from .sources.unpaywall_source import UnpaywallSource
from .utils.logging import get_logger
from .utils.retry import RetryConfig

logger = get_logger(__name__)


class SciHubClient:
    """Main client interface with multi-source support (Sci-Hub, Unpaywall, arXiv, CORE)."""

    def __init__(
        self,
        output_dir: str = None,
        mirrors: list[str] = None,
        timeout: int = None,
        retries: int = None,
        email: str = None,
        mirror_manager: MirrorManager = None,
        parser: ContentParser = None,
        file_manager: FileManager = None,
        downloader: FileDownloader = None,
        source_manager: SourceManager = None,
        convert_to_md: bool = False,
        md_output_dir: str | None = None,
        md_backend: str = "pymupdf4llm",
        md_strict: bool = True,
        md_overwrite: bool = False,
        md_converter: PdfToMarkdownConverter | None = None,
    ):
        """Initialize client with optional dependency injection."""

        # Configuration
        self.output_dir = output_dir or settings.output_dir
        self.timeout = timeout or settings.timeout
        self.retry_config = RetryConfig(max_attempts=retries or settings.retries)
        self.email = email or settings.email

        self.convert_to_md = convert_to_md
        self.md_output_dir = md_output_dir
        self.md_backend = md_backend
        self.md_strict = md_strict
        self.md_overwrite = md_overwrite
        self.md_converter = md_converter

        # Dependency injection with defaults
        self.mirror_manager = mirror_manager or MirrorManager(mirrors, self.timeout)
        self.parser = parser or ContentParser()
        self.file_manager = file_manager or FileManager(self.output_dir)
        self.downloader = downloader or FileDownloader(BasicSession(self.timeout))

        # DOI processor (stateless)
        self.doi_processor = DOIProcessor()

        # Multi-source support
        if source_manager is None:
            # Initialize paper sources
            sources = [
                SciHubSource(
                    mirror_manager=self.mirror_manager,
                    parser=self.parser,
                    doi_processor=self.doi_processor,
                    downloader=self.downloader,
                )
            ]

            # Direct URL sources: enable direct PDF and PMC handling for URL inputs
            sources.insert(0, HTMLLandingSource(downloader=self.downloader))
            sources.insert(0, PMCSource(downloader=self.downloader))
            sources.insert(0, DirectPDFSource())

            # arXiv: Free and open, always enabled (high priority for preprints)
            sources.insert(0, ArxivSource(timeout=self.timeout))

            # Only enable Unpaywall when email is provided
            if self.email:
                sources.insert(0, UnpaywallSource(email=self.email, timeout=self.timeout))

            # CORE does not require email, keep as OA fallback
            sources.append(CORESource(api_key=settings.core_api_key, timeout=self.timeout))

            self.source_manager = SourceManager(
                sources=sources,
                year_threshold=settings.year_threshold,
                enable_year_routing=settings.enable_year_routing,
            )
        else:
            self.source_manager = source_manager

    def download_paper(
        self, identifier: str, progress_callback: Optional[ProgressCallback] = None
    ) -> DownloadResult:
        """
        Download a paper given its DOI or URL.

        Uses fine-grained retry at lower layers (download, API calls).
        No coarse-grained retry at this level.
        """
        doi = self.doi_processor.normalize_doi(identifier)
        logger.info(f"Downloading paper: {doi}")

        return self._download_single_paper(
            identifier=identifier, normalized_identifier=doi, progress_callback=progress_callback
        )

    def _download_single_paper(
        self,
        identifier: str,
        normalized_identifier: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> DownloadResult:
        """
        Single download attempt using multi-source manager.

        Gets URL and metadata in one pass to avoid duplicate API calls.
        """
        start_time = time.time()

        def _build_result(
            *,
            success: bool,
            file_path: Optional[str] = None,
            file_size: Optional[int] = None,
            metadata: Optional[dict] = None,
            source: Optional[str] = None,
            download_url: Optional[str] = None,
            error: Optional[str] = None,
            md_path: str | None = None,
            md_success: bool | None = None,
            md_error: str | None = None,
        ) -> DownloadResult:
            title = metadata.get("title") if isinstance(metadata, dict) else None
            year = metadata.get("year") if isinstance(metadata, dict) else None
            return DownloadResult(
                identifier=identifier,
                normalized_identifier=normalized_identifier,
                success=success,
                file_path=file_path,
                file_size=file_size,
                source=source,
                metadata=metadata,
                title=title,
                year=year,
                download_url=download_url,
                download_time=time.time() - start_time,
                error=error,
                md_path=md_path,
                md_success=md_success,
                md_error=md_error,
            )

        # Get PDF URL and metadata together (avoids duplicate API calls)
        download_url, metadata, source = self.source_manager.get_pdf_url_with_metadata(
            normalized_identifier
        )

        if not download_url:
            error = f"Could not find PDF URL for {normalized_identifier} from any source"
            logger.error(error)
            return _build_result(
                success=False,
                metadata=metadata,
                source=source,
                error=error,
            )

        logger.debug(f"Download URL: {download_url}")

        # Generate filename from metadata if available
        filename = self._generate_filename(normalized_identifier, metadata)
        output_path = self.file_manager.get_output_path(filename)

        progress_state = {"bytes": 0, "total": None}

        def _handle_progress(bytes_downloaded: int, total_bytes: Optional[int]) -> None:
            progress_state["bytes"] = bytes_downloaded
            progress_state["total"] = total_bytes
            if progress_callback:
                progress_callback(
                    DownloadProgress(
                        identifier=identifier,
                        url=download_url,
                        bytes_downloaded=bytes_downloaded,
                        total_bytes=total_bytes,
                        done=False,
                    )
                )

        # Download the PDF (with automatic retry at download layer)
        success, error_msg = self.downloader.download_file(
            download_url,
            output_path,
            progress_callback=_handle_progress if progress_callback else None,
        )
        if progress_callback:
            progress_callback(
                DownloadProgress(
                    identifier=identifier,
                    url=download_url,
                    bytes_downloaded=progress_state["bytes"],
                    total_bytes=progress_state["total"],
                    done=True,
                )
            )
        if not success:
            # If Sci-Hub download failed, invalidate mirror cache
            if "sci-hub" in download_url.lower():
                logger.warning("Sci-Hub download failed, invalidating mirror cache")
                scihub = [s for s in self.source_manager.sources.values() if s.name == "Sci-Hub"]
                if scihub:
                    scihub[0].mirror_manager.invalidate_cache()

            error_msg = error_msg or "Download failed"
            logger.error(f"Failed to download {normalized_identifier}: {error_msg}")
            return _build_result(
                success=False,
                metadata=metadata,
                source=source,
                download_url=download_url,
                error=error_msg,
            )

        # Validate file
        if not self.file_manager.validate_file(output_path):
            error = "Downloaded file validation failed"
            logger.error(error)
            return _build_result(
                success=False,
                metadata=metadata,
                source=source,
                download_url=download_url,
                error=error,
            )

        md_path: str | None = None
        md_success: bool | None = None
        md_error: str | None = None
        if self.convert_to_md:
            try:
                md_path, md_success, md_error = self._convert_pdf_to_markdown(output_path)
            except Exception as e:
                md_success = False
                md_error = str(e)

        file_size = os.path.getsize(output_path)
        logger.info(f"Successfully downloaded {normalized_identifier} ({file_size} bytes)")
        return _build_result(
            success=True,
            file_path=output_path,
            file_size=file_size,
            metadata=metadata,
            source=source,
            download_url=download_url,
            md_path=md_path,
            md_success=md_success,
            md_error=md_error,
        )

    def _convert_pdf_to_markdown(self, pdf_path: str) -> tuple[str | None, bool | None, str | None]:
        from pathlib import Path

        from .converters.pdf_to_md import MarkdownConvertOptions

        pdf = Path(pdf_path)
        output_dir = Path(self.md_output_dir) if self.md_output_dir else pdf.parent / "md"
        md_path = output_dir / f"{pdf.stem}.md"
        output_dir.mkdir(parents=True, exist_ok=True)

        if md_path.exists() and not self.md_overwrite:
            return str(md_path), True, None

        backend = (self.md_backend or "pymupdf4llm").lower().strip()
        converter = self.md_converter
        if converter is None:
            if backend != "pymupdf4llm":
                return str(md_path), False, f"Unsupported markdown backend: {self.md_backend}"
            from .converters.pymupdf4llm_converter import Pymupdf4llmConverter

            converter = Pymupdf4llmConverter()

        ok, error = converter.convert(
            str(pdf),
            str(md_path),
            options=MarkdownConvertOptions(overwrite=self.md_overwrite),
        )
        if not ok:
            return str(md_path), False, error or "Markdown conversion failed"
        return str(md_path), True, None

    def _generate_filename(self, doi: str, metadata: Optional[dict]) -> str:
        """
        Generate filename from metadata or DOI.

        Args:
            doi: The DOI
            metadata: Optional metadata dict from source

        Returns:
            Generated filename
        """
        if metadata and metadata.get("title"):
            try:
                from .metadata_utils import generate_filename_from_metadata

                return generate_filename_from_metadata(
                    metadata.get("title", ""), metadata.get("year", ""), doi
                )
            except Exception as e:
                logger.debug(f"Could not generate filename from metadata: {e}")

        # If the identifier is a URL (e.g., direct PDF link), use URL-based naming.
        from urllib.parse import urlparse

        parsed = urlparse(doi)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return self.file_manager.generate_filename_from_url(doi)

        # Fallback to DOI-based filename
        return self.file_manager.generate_filename(doi, html_content=None)

    def download_from_file(
        self,
        input_file: str,
        parallel: int = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> list[DownloadResult]:
        """Download papers from a file containing DOIs or URLs."""
        parallel = parallel or settings.parallel
        parallel = max(1, parallel)

        # Read input file
        try:
            with open(input_file, encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            logger.error(f"Error reading input file: {e}")
            return []

        # Filter out comments and empty lines
        identifiers = [
            line.strip() for line in lines if line.strip() and not line.strip().startswith("#")
        ]

        logger.info(f"Found {len(identifiers)} papers to download")

        if parallel == 1 or len(identifiers) <= 1:
            results = []
            for i, identifier in enumerate(identifiers):
                logger.info(f"Processing {i + 1}/{len(identifiers)}: {identifier}")
                result = self.download_paper(identifier, progress_callback=progress_callback)
                results.append(result)

                # Add a small delay between sequential downloads
                if i < len(identifiers) - 1:
                    time.sleep(2)
        else:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            results: list[Optional[DownloadResult]] = [None] * len(identifiers)
            workers = min(parallel, len(identifiers))
            logger.info(f"Downloading {len(identifiers)} papers with {workers} workers")

            def _download_one(index: int, identifier: str) -> tuple[int, DownloadResult]:
                return index, self.download_paper(identifier, progress_callback=progress_callback)

            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_index = {
                    executor.submit(_download_one, index, identifier): index
                    for index, identifier in enumerate(identifiers)
                }
                for future in as_completed(future_to_index):
                    index, result = future.result()
                    results[index] = result

            results = [result for result in results if result is not None]

        successful = sum(1 for result in results if result.success)
        logger.info(f"Downloaded {successful}/{len(identifiers)} papers")

        return results
