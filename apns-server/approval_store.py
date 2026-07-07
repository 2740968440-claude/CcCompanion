"""
Approval store — 审批事件生命周期管理

每条 schema:
{
  "id": "approval-20260706-001",
  "ts": "2026-07-06T17:30:00.123+08:00",
  "command": "rm /tmp/test",
  "display": "rm /tmp/test",
  "status": "pending" | "approved_waiting_prompt" | "approved" | "denied",
  "updated_at": "2026-07-06T17:30:05.456+08:00"
}

生命周期:
  pending → approved_waiting_prompt → approved
  pending → denied

PreToolUse hook 创建 pending 事件。
用户点允许 → approved_waiting_prompt（等tmux prompt就绪）。
检测到prompt → 注入y → approved。
用户点拒绝 → denied（直接注n，不等prompt）。
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("cc-apns-server.approval_store")

VALID_STATUSES = {"pending", "approved_waiting_prompt", "approved", "denied"}


class ApprovalStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _tz(self) -> timezone:
        return timezone(timedelta(hours=8))

    def _now(self) -> str:
        return datetime.now(self._tz()).isoformat(timespec="milliseconds")

    def _gen_id(self) -> str:
        """Generate unique approval ID: approval-YYYYMMDD-NNN"""
        today = datetime.now(self._tz()).strftime("%Y%m%d")
        suffix = uuid.uuid4().hex[:4]
        return f"approval-{today}-{suffix}"

    def create(self, command: str, display: str | None = None) -> dict[str, Any]:
        """Create a new pending approval event."""
        event: dict[str, Any] = {
            "id": self._gen_id(),
            "ts": self._now(),
            "command": command,
            "display": display or command[:80],
            "status": "pending",
            "updated_at": self._now(),
        }
        self._append(event)
        self._cleanup_expired()
        logger.info("approval created id=%s cmd=%s", event["id"], event["display"])
        return event

    def update(self, approval_id: str, status: str) -> dict[str, Any] | None:
        """Update approval status. Returns updated event or None if not found.

        Valid transitions:
        - pending → approved_waiting_prompt (user tapped allow, waiting for prompt)
        - pending → denied (user tapped deny)
        - approved_waiting_prompt → approved (prompt detected, input injected)
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")

        with self._lock:
            events = self._read_all()
            found = None
            for e in events:
                if e["id"] == approval_id:
                    found = e
                    break

            if found is None:
                logger.warning("approval not found id=%s", approval_id)
                return None

            # validate transition
            current = found["status"]
            valid_transitions = {
                "pending": {"approved_waiting_prompt", "denied"},
                "approved_waiting_prompt": {"approved"},
            }
            allowed = valid_transitions.get(current, set())
            if status not in allowed:
                logger.warning(
                    "approval invalid transition id=%s %s → %s (allowed: %s)",
                    approval_id, current, status, allowed,
                )
                return None

            found["status"] = status
            found["updated_at"] = self._now()
            self._write_all(events)

        logger.info("approval updated id=%s %s → %s", approval_id, current, status)
        return dict(found)

    def get(self, approval_id: str) -> dict[str, Any] | None:
        """Get a single approval event by ID."""
        with self._lock:
            events = self._read_all()
            for e in events:
                if e["id"] == approval_id:
                    return dict(e)
        return None

    def list_pending(self) -> list[dict[str, Any]]:
        """List all non-terminal approvals (pending + approved_waiting_prompt)."""
        with self._lock:
            events = self._read_all()
            return [e for e in events if e["status"] in ("pending", "approved_waiting_prompt")]

    def list_waiting_prompt(self) -> list[dict[str, Any]]:
        """List approvals in approved_waiting_prompt state (need prompt detection)."""
        with self._lock:
            events = self._read_all()
            return [e for e in events if e["status"] == "approved_waiting_prompt"]

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent approvals (all statuses)."""
        with self._lock:
            events = self._read_all()
            return events[-limit:]

    def _cleanup_expired(self):
        """Remove terminal events older than 1 hour."""
        with self._lock:
            events = self._read_all()
            cutoff = datetime.now(self._tz()) - timedelta(hours=1)
            kept = []
            removed = 0
            for e in events:
                try:
                    ts = datetime.fromisoformat(e["ts"])
                except Exception:
                    kept.append(e)
                    continue
                if e["status"] in ("approved", "denied") and ts < cutoff:
                    removed += 1
                else:
                    kept.append(e)
            if removed:
                self._write_all(kept)
                logger.debug("approval cleanup: removed %d expired", removed)

    # ---- internal ----

    def _read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("approval: skip bad line: %s", line[:80])
        return events

    def _write_all(self, events: list[dict[str, Any]]):
        with open(self.path, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def _append(self, event: dict[str, Any]):
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
