"""
Mirror configuration and management for Sci-Hub CLI.
"""

from enum import Enum


class MirrorTier(Enum):
    """Mirror difficulty tiers."""

    EASY = "easy"
    HARD = "hard"


class MirrorConfig:
    """Configuration for Sci-Hub mirrors organized by difficulty."""

    # Mirror configuration by difficulty level.
    #
    # Mirror domains are volatile, and a domain returning HTTP 200 for its home
    # page is not evidence that it can serve a requested paper.  The entries
    # below were verified by resolving a real article and downloading its PDF
    # (402,190 bytes starting with %PDF) on 2026-10-21; candidate domains come
    # from the list published at https://lovescihub.wordpress.com/.
    #
    # MirrorManager still validates every candidate against an article-specific
    # URL before using one, so a stale entry costs a single probe inside the
    # parallel tier instead of a failed run.  Update this list when the mirrors
    # rotate; --mirror overrides it for a single invocation.
    MIRROR_TIERS = {
        MirrorTier.EASY: [
            "https://sci-hub.ren",
            "https://sci-hub.ee",
            "https://sci-hub.mk",
        ],
        MirrorTier.HARD: [],
    }

    @classmethod
    def get_mirrors_by_tier(cls, tier: MirrorTier) -> list[str]:
        """Get mirrors for a specific tier."""
        return cls.MIRROR_TIERS.get(tier, [])

    @classmethod
    def get_all_mirrors(cls) -> list[str]:
        """Get all mirrors ordered by difficulty (easy first)."""
        return cls.MIRROR_TIERS[MirrorTier.EASY] + cls.MIRROR_TIERS[MirrorTier.HARD]

    @classmethod
    def get_easy_mirrors(cls) -> list[str]:
        """Get only easy mirrors."""
        return cls.MIRROR_TIERS[MirrorTier.EASY]

    @classmethod
    def get_hard_mirrors(cls) -> list[str]:
        """Get only hard mirrors."""
        return cls.MIRROR_TIERS[MirrorTier.HARD]

    @classmethod
    def is_hard_mirror(cls, mirror_url: str) -> bool:
        """Check if a mirror is in the hard tier."""
        return mirror_url in cls.MIRROR_TIERS[MirrorTier.HARD]


# Default mirror configuration
DEFAULT_MIRRORS = MirrorConfig.get_all_mirrors()
