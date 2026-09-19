"""Expose exact domain codecs and strict immutable wire records."""

# project library imports
from serialization.codec import DomainCodec
from serialization.records import WireRecord

__all__ = ["DomainCodec", "WireRecord"]
