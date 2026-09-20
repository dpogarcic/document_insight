"""Typed results exchanged by document parsing adapters and workers."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Text extracted from one immutable document version."""

    text: str
    page_count: int
    parser_name: str
    parser_version: str
