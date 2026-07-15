"""Booking providers (Resy, OpenTable) behind a common interface."""
from .base import BookingProvider, BookingResult
from .resy import ResyProvider
from .opentable import OpenTableProvider

PROVIDERS = {
    "resy": ResyProvider,
    "opentable": OpenTableProvider,
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
    "OpenTableProvider",
    "PROVIDERS",
    "get_provider",
]
