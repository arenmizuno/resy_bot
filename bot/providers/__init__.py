"""Booking providers behind a common interface.

Resy is the only supported platform; see the README's limitations section for
why OpenTable was removed.
"""
from .base import BookingProvider, BookingResult
from .resy import ResyProvider

PROVIDERS = {
    "resy": ResyProvider,
}


def get_provider(platform):
    """Return an instantiated provider for the given platform name."""
    try:
        return PROVIDERS[platform]()
    except KeyError:
        raise ValueError(f"Unknown platform: {platform!r}")


__all__ = [
    "BookingProvider",
    "BookingResult",
    "ResyProvider",
    "PROVIDERS",
    "get_provider",
]
