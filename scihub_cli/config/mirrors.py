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

    # Mirror configuration by difficulty level
    MIRROR_TIERS = {
        MirrorTier.EASY: [  # No Cloudflare protection, use basic requests
            "https://www.sci-hub.ee",
            "https://sci-hub.ru",
            "https://sci-hub.ren",
            "https://sci-hub.wf",
            "https://sci-hub.st",  # Alternative domain
            "https://sci-hub.do",  # Alternative domain
            "https://sci-hub.tf",  # Alternative domain
            "https://sci-hub.shop",  # Alternative domain
            "https://sci-hub.mksa.top",  # Alternative domain
        ],
        MirrorTier.HARD: [  # Strong Cloudflare protection, needs advanced bypass
            "https://sci-hub.se",  # The final boss
        ],
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
