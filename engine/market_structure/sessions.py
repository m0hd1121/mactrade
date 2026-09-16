"""Trading-session classification from raw bar timestamps (UTC).

Purely time/price derived -- no indicators. Session boundaries are configured
in hours (UTC) and default to the broadly-accepted Forex session windows;
they are adjustable in Settings so users can match their broker's server-time
offset.
"""
from __future__ import annotations

from datetime import datetime

from engine.config import SessionConfig
from engine.types import Session


def _in_range(start: int, end: int, hour: int) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps past midnight (e.g. Asian session)


def classify_session(dt: datetime, cfg: SessionConfig) -> Session:
    hour = dt.hour
    if _in_range(cfg.new_york_start_utc, cfg.new_york_end_utc, hour):
        return Session.NEW_YORK
    if _in_range(cfg.london_start_utc, cfg.london_end_utc, hour):
        return Session.LONDON
    if _in_range(cfg.asian_start_utc, cfg.asian_end_utc, hour):
        return Session.ASIAN
    return Session.OFF_HOURS
