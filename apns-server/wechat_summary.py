"""微信时间线摘要 — stub (原模块丢失，2026-07-06 18:10).

原功能：根据日期和群组加载微信消息摘要。模块文件在 push.py 重启前已丢失，
但因旧进程未重启而未暴露。此处提供最小 stub 使 push.py 能启动。
"""

import logging
logger = logging.getLogger("cc-apns-server.wechat_summary")


def load_config() -> dict:
    return {"groups": []}


def get_available_dates(group: str | None = None) -> list[str]:
    return []


def load_summaries(date: str, group: str | None = None) -> list[dict]:
    return []


def start_hourly_thread():
    """stub: 不启动后台线程"""
    pass
