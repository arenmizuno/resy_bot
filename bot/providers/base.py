"""Provider interface.

The poller only knows about `BookingProvider.book(request) -> BookingResult`;
each platform hides its own Selenium flow behind that. Providers should never
raise for an ordinary "no table available" outcome — they return a
BookingResult with success=False so the poller can retry later. Exceptions are
reserved for genuinely unexpected failures.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class BookingResult:
    success: bool
    slot: Optional[str] = None       # the time actually booked, e.g. "7:15 PM"
    error: Optional[str] = None      # human-readable reason when not booked
    no_availability: bool = False    # True = nothing in window yet (soft, retry)

    @classmethod
    def booked(cls, slot):
        return cls(success=True, slot=slot)

    @classmethod
    def unavailable(cls, message="No slots available within the desired window."):
        return cls(success=False, error=message, no_availability=True)

    @classmethod
    def failed(cls, message):
        return cls(success=False, error=message)


class BookingProvider(ABC):
    """Base class for a reservation platform."""

    name = "base"

    @abstractmethod
    def book(self, request) -> BookingResult:
        """Attempt to book `request` (a dict from the store). Returns a result."""
        raise NotImplementedError
