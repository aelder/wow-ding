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


def verify_secret(secret, channel=None):
    path = webhook_path(secret).split("?")[0]
    conn = http.client.HTTPSConnection("discord.com", timeout=10)
    try:
        conn.request("GET", path, headers={"User-Agent": "WoW-Ding/1.1"})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError(f"Discord returned HTTP {response.status}. Check the webhook and try again.")
        metadata = json.loads(response.read(64_000))
        if channel and metadata.get("channel_id") != channel:
            raise ValueError("Please use the webhook for your existing WoW Ding channel.")
        if not isinstance(metadata.get("channel_id"), str) or not metadata["channel_id"].isascii() or not metadata["channel_id"].isdigit():
            raise ValueError("Choose a webhook for a Discord text channel.")
        return metadata["channel_id"]
    finally:
        conn.close()


def delay_seconds(value) -> float:
    try:
        delay = float(value)
        return delay if math.isfinite(delay) and delay > 0 else 0
    except (ValueError, TypeError, OverflowError):
        return 0


def post(path: str, level: int, name: str | None = None, ping: bool = False):
    if ping:
        content = f"Test ding! {name} is level {level} in WoW."
    elif name:
        content = f"Ding! {name} reached level {level} in WoW."
    else:
        content = f"Ding! Reached level {level} in WoW."
    body = json.dumps({"content": content,
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
