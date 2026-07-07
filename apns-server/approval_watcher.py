#!/usr/bin/env python3
"""
审批 prompt 检测与 tmux 注入。

由 push.py 在收到 POST /approval 时调用，或作为后台线程独立运行。

工作方式:
  1. 轮询 tmux capture-pane（每 0.5s）
  2. 检测 Claude Code 是否显示权限提示
  3. 检测到 → 注入 y/n → 更新审批状态

检测模式（按优先级）:
  - "Do you want to proceed" — Claude Code 标准权限提示
  - 超时 15s 后退

用法:
  python3 approval_watcher.py <approval_id> <action> <tmux_session>
  python3 approval_watcher.py approval-20260706-a1b2 allow cc-tg
  python3 approval_watcher.py approval-20260706-a1b2 deny cc-tg

也支持后台线程模式:
  ApprovalWatcher(state, approval_store).start()
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("cc-apns-server.approval_watcher")

PROMPT_PATTERNS = [
    "Do you want to proceed",
    "permission",
]

POLL_INTERVAL = 0.5  # seconds
TIMEOUT = 15  # seconds


def _tz() -> timezone:
    return timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(_tz()).isoformat(timespec="milliseconds")


def capture_tmux(session: str = "cc-tg", lines: int = 20) -> str:
    """Capture last N lines of tmux pane."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session, "-p", "-S", f"-{lines}"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout
    except Exception as e:
        logger.warning("tmux capture failed: %s", e)
        return ""


def is_prompt_ready(session: str = "cc-tg") -> bool:
    """Check if Claude Code is currently displaying an approval prompt."""
    text = capture_tmux(session, lines=20)
    if not text:
        return False

    text_lower = text.lower()
    for pattern in PROMPT_PATTERNS:
        if pattern.lower() in text_lower:
            return True
    return False


def inject_tmux(session: str, key: str, enter: bool = True) -> bool:
    """Inject a key sequence into tmux session."""
    try:
        args = ["tmux", "send-keys", "-t", session, key]
        if enter:
            args.append("Enter")
        subprocess.run(args, capture_output=True, timeout=5)
        logger.info("tmux injected: %s → %s%s", session, key, " Enter" if enter else "")
        return True
    except Exception as e:
        logger.error("tmux inject failed: %s", e)
        return False


def wait_and_inject(
    approval_id: str,
    action: str,  # "allow" or "deny"
    session: str = "cc-tg",
    approval_store_path: str | None = None,
) -> dict[str, Any]:
    """
    Wait for the permission prompt to appear, then inject y/n into tmux.

    Returns: {"ok": bool, "status": str, "detail": str}

    For "deny": inject immediately (rejecting doesn't need to wait for prompt).
    For "allow": wait for prompt, then inject.

    If approval_store_path is provided, the approval event status is updated.
    """
    from approval_store import ApprovalStore

    store = None
    if approval_store_path:
        store = ApprovalStore(approval_store_path)

    if action == "deny":
        # Deny: inject immediately, no need to wait for prompt
        ok = inject_tmux(session, "n")
        status = "denied" if ok else "pending"
        if store and ok:
            store.update(approval_id, "denied")
        return {
            "ok": ok,
            "status": status,
            "detail": "denied and n injected" if ok else "tmux inject failed",
        }

    # Allow: need to wait for prompt
    start = time.time()
    last_capture = ""
    while time.time() - start < TIMEOUT:
        if is_prompt_ready(session):
            # Small extra delay so Claude Code is definitely ready
            time.sleep(0.3)
            ok = inject_tmux(session, "y")
            status = "approved" if ok else "approved_waiting_prompt"
            if store and ok:
                store.update(approval_id, "approved")
            return {
                "ok": ok,
                "status": status,
                "detail": f"prompt detected after {time.time() - start:.1f}s, y injected" if ok else "tmux inject failed after prompt found",
            }
        time.sleep(POLL_INTERVAL)

    # Timeout
    logger.warning("approval prompt timeout id=%s after %.0fs", approval_id, time.time() - start)
    return {
        "ok": False,
        "status": "approved_waiting_prompt",
        "detail": f"prompt not detected within {TIMEOUT}s, staying in approved_waiting_prompt",
    }


# ---- background daemon mode ----
# Polls for approved_waiting_prompt events and tries to inject them.

class ApprovalWatcherDaemon:
    """Background thread that watches for approved_waiting_prompt events
    and completes the injection when the prompt appears."""

    def __init__(self, store):
        self.store = store
        self._running = False
        self._thread = None

    def start(self):
        import threading
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
        logger.info("approval watcher daemon started")

    def stop(self):
        self._running = False

    def _poll(self):
        while self._running:
            try:
                waiting = self.store.list_waiting_prompt()
                for evt in waiting:
                    if is_prompt_ready():
                        ok = inject_tmux("cc-tg", "y")
                        if ok:
                            self.store.update(evt["id"], "approved")
                            logger.info("daemon injected approval id=%s", evt["id"])
            except Exception:
                logger.exception("approval watcher daemon error")
            time.sleep(POLL_INTERVAL)


# ---- CLI mode ----

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("usage: approval_watcher.py <approval_id> <allow|deny> [session] [store_path]")
        sys.exit(1)

    aid = sys.argv[1]
    act = sys.argv[2]
    sess = sys.argv[3] if len(sys.argv) > 3 else "cc-tg"
    spath = sys.argv[4] if len(sys.argv) > 4 else None

    result = wait_and_inject(aid, act, sess, spath)
    print(json.dumps(result, ensure_ascii=False))
