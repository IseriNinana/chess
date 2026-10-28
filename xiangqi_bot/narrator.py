"""把即将走的棋通知鲸鱼娘（douyin-live Overlay HTTP）。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class MoveNarrator:
    def __init__(
        self,
        url: str = "http://127.0.0.1:3210/xiangqi",
        timeout_s: float = 2.0,
        delay_s: float = 5.0,
        enabled: bool = True,
    ):
        self.url = url
        self.timeout_s = timeout_s
        self.delay_s = delay_s
        self.enabled = enabled

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> "MoveNarrator":
        n = cfg or {}
        return cls(
            url=str(n.get("url") or "http://127.0.0.1:3210/xiangqi"),
            timeout_s=float(n.get("timeout_s", 2.0)),
            delay_s=float(n.get("delay_s", 5.0)),
            enabled=bool(n.get("enabled", True)),
        )

    def announce(
        self,
        fen: str,
        move: str,
        move_zh: str,
        side: str | None = None,
    ) -> bool:
        """通知成功返回 True（调用方再 sleep delay_s）。失败只打日志。"""
        if not self.enabled:
            return False
        payload: dict[str, Any] = {
            "fen": fen,
            "move": move,
            "moveZh": move_zh,
        }
        if side:
            payload["side"] = side
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                if 200 <= int(resp.status) < 300:
                    print(
                        f"已通知鲸鱼娘: {move_zh}  FEN={fen}",
                        flush=True,
                    )
                    return True
                print(
                    f"鲸鱼娘返回 HTTP {resp.status}，跳过解说等待",
                    flush=True,
                )
                return False
        except urllib.error.HTTPError as exc:
            print(f"鲸鱼娘拒绝解说 HTTP {exc.code}，跳过等待", flush=True)
            return False
        except Exception as exc:
            print(f"未连上鲸鱼娘（{exc}），直接走子", flush=True)
            return False
