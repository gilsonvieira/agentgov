"""Refunds agent — the end-to-end example.

Demonstrates the full loop: a typed ``issue_refund`` tool, a ``refund-cap`` rail
that rolls back over-cap calls, and a checkpoint that pauses large refunds for a
human decision.
"""

from __future__ import annotations
