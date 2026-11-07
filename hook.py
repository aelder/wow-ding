"""Send a single, fixed-shape Discord message. Never log the webhook URL."""
import http.client
import json
import math
import re


class Retry(Exception):
    def __init__(self, delay=0):
        self.delay = delay


class Rejected(Exception):
    pass


def webhook_path(url: str) -> str:
    match = re.fullmatch(r"https://discord\.com(/api/webhooks/[0-9]+/[A-Za-z0-9_-]+)", url)
    if not match:
        raise ValueError("Use a Discord channel webhook URL on discord.com.")
    return match[1] + "?wait=true"


def delay_seconds(value) -> float:
    try:
        delay = float(value)
        return delay if math.isfinite(delay) and delay > 0 else 0
    except (ValueError, TypeError, OverflowError):
        return 0


def post(path: str, level: int):
    body = json.dumps({"content": f"Ding! Reached level {level} in WoW.",
                       "allowed_mentions": {"parse": []}})
    conn = http.client.HTTPSConnection("discord.com", timeout=10)
    try:
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json",
                                                     "User-Agent": "WoW-Ding/1.0"})
        response = conn.getresponse()
        if response.status == 429:
            delay = delay_seconds(response.getheader("Retry-After"))
            try:
                reply = json.loads(response.read(8192))
                if isinstance(reply, dict):
                    delay = max(delay, delay_seconds(reply.get("retry_after")))
            except (ValueError, UnicodeError):
                pass
            raise Retry(delay)
        if response.status >= 500 or response.status == 408:
            raise Retry()
        if not 200 <= response.status < 300:
            raise Rejected(f"Discord returned HTTP {response.status}. Check the channel webhook.")
    except (OSError, http.client.HTTPException):
        raise Retry() from None
    finally:
        conn.close()
