"""
upload/quota_tracker.py
=======================
Pre-upload quota gate that prevents the pipeline from attempting a
YouTube upload when the active client's daily unit budget is too low.

YouTube Data API v3 free-tier quota
-------------------------------------
10 000 units per project per day (UTC reset).
Cost per operation:
  video.insert  (upload)  : 1 600 units
  video.list              :   1 unit
  playlistItems.insert    :  50 units

At 1 600 units/upload, one project supports a maximum of 6 uploads/day.
With 3 rotating projects (3 × 6 = 18 headroom), 4 Shorts + 1 compilation
per day is comfortably within limits.

This module wraps db.py's quota helpers with a higher-level pre-flight
check and a post-upload deduction so the rest of the upload stack stays
quota-aware without coupling to DB internals.
"""

from typing import Optional

from database.db import Database
from utils.logger import get_logger

logger = get_logger(__name__)

# YouTube API unit cost constants
UNITS_VIDEO_INSERT:        int = 1_600
UNITS_VIDEO_LIST:          int = 1
UNITS_PLAYLIST_INSERT:     int = 50
UNITS_DAILY_LIMIT:         int = 10_000

# Safety buffer — stop uploading when remaining units drop below this
UNITS_SAFETY_BUFFER:       int = 200


class QuotaTracker:
    """
    Wraps db.py quota helpers with pre/post upload accounting logic.

    Parameters
    ----------
    db : Shared Database instance.
    """

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db or Database()
        self._db.init()

    # ── Pre-upload gate ─────────────────────────────────────────────────────

    def can_upload(self, client_index: int, operation: str = "video.insert") -> bool:
        """
        Return True if the client has enough remaining quota for `operation`.

        Parameters
        ----------
        client_index : 1-based YouTube OAuth client index.
        operation    : API operation name — key into UNIT_COSTS dict.

        Returns
        -------
        bool — True = safe to proceed; False = skip this client.
        """
        cost = self._operation_cost(operation)
        quota = self._db.get_quota_today(client_index)
        remaining = quota["units_limit"] - quota["units_used"]
        safe_remaining = remaining - UNITS_SAFETY_BUFFER

        allowed = safe_remaining >= cost

        if not allowed:
            logger.warning(
                "QuotaTracker: client %d BLOCKED — remaining=%d buffer=%d "
                "needed=%d  operation=%s",
                client_index, remaining, UNITS_SAFETY_BUFFER, cost, operation,
            )
        else:
            logger.debug(
                "QuotaTracker: client %d OK — remaining=%d needed=%d  operation=%s",
                client_index, remaining, cost, operation,
            )

        return allowed

    # ── Post-upload accounting ───────────────────────────────────────────────

    def record_upload(self, client_index: int) -> None:
        """
        Deduct the cost of one video.insert from today's quota ledger.
        Call this immediately after a successful upload API call.
        """
        self._db.log_quota_usage(
            yt_client_index=client_index,
            units_used=UNITS_VIDEO_INSERT,
            units_limit=UNITS_DAILY_LIMIT,
        )
        quota = self._db.get_quota_today(client_index)
        logger.info(
            "QuotaTracker: upload recorded — client=%d used=%d/%d remaining=%d",
            client_index,
            quota["units_used"],
            quota["units_limit"],
            quota["units_limit"] - quota["units_used"],
        )

    def record_operation(self, client_index: int, operation: str) -> None:
        """
        Deduct the cost of any named API operation (e.g. video.list).

        Parameters
        ----------
        client_index : 1-based client index.
        operation    : Operation name key.
        """
        cost = self._operation_cost(operation)
        self._db.log_quota_usage(
            yt_client_index=client_index,
            units_used=cost,
            units_limit=UNITS_DAILY_LIMIT,
        )
        logger.debug(
            "QuotaTracker: %s recorded — client=%d cost=%d",
            operation, client_index, cost,
        )

    # ── Status reporting ─────────────────────────────────────────────────────

    def status_report(self) -> list[dict]:
        """
        Return quota status for all clients (used by pipeline startup logging).

        Returns
        -------
        List of dicts with keys: client_index, used, limit, remaining, pct_used.
        """
        report = []
        for idx in range(1, 4):
            q = self._db.get_quota_today(idx)
            used      = q["units_used"]
            limit     = q["units_limit"]
            remaining = limit - used
            report.append({
                "client_index": idx,
                "used":         used,
                "limit":        limit,
                "remaining":    remaining,
                "pct_used":     round(used / limit * 100, 1),
                "uploads_left": remaining // UNITS_VIDEO_INSERT,
            })
        return report

    def log_status_report(self) -> None:
        """Write the quota status report to the logger (INFO level)."""
        for row in self.status_report():
            logger.info(
                "Quota | client=%d | %d/%d units used (%.1f%%) | "
                "~%d uploads remaining today",
                row["client_index"],
                row["used"],
                row["limit"],
                row["pct_used"],
                row["uploads_left"],
            )

    def uploads_remaining_today(self, client_index: int) -> int:
        """Return estimated remaining upload capacity for one client."""
        q = self._db.get_quota_today(client_index)
        remaining = q["units_limit"] - q["units_used"] - UNITS_SAFETY_BUFFER
        return max(0, remaining // UNITS_VIDEO_INSERT)

    def total_uploads_remaining_today(self) -> int:
        """Sum of upload capacity across all 3 clients."""
        return sum(self.uploads_remaining_today(i) for i in range(1, 4))

    # ── Internal ─────────────────────────────────────────────────────────────

    @staticmethod
    def _operation_cost(operation: str) -> int:
        _COSTS = {
            "video.insert":        UNITS_VIDEO_INSERT,
            "video.list":          UNITS_VIDEO_LIST,
            "playlistItems.insert": UNITS_PLAYLIST_INSERT,
        }
        cost = _COSTS.get(operation)
        if cost is None:
            logger.warning(
                "QuotaTracker: unknown operation '%s' — assuming %d units.",
                operation, UNITS_VIDEO_INSERT,
            )
            return UNITS_VIDEO_INSERT
        return cost
