import os
import time
from typing import Optional
import httpx
from fastapi import FastAPI, Request, Response

app = FastAPI()

# --- Config ---
GROUP_CHAT_ID = -1001866962075
BOT_USERNAME = "turbotaautomationbot"
BOT_ID = 8662984452
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8662984452:AAGp7Ewudyv-kMRtmeiKdnv7iZD9mohpV9s")
BASE44_BASE = "https://app.base44.com/api/agents/69cfa85cc1cb5d9be0b98f3c"
BASE44_API_KEY = os.environ.get("BASE44_API_KEY", "cc98d8b4eca243de93f5eb9fd8b57d88")
CONV_ID = os.environ.get("BASE44_CONV_ID", "69cfa85e6e1663b653e71819")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Track active conversations: {user_id: expiry_timestamp}
# After bot asks a question, listen to that user for 10 minutes without tag
active_users: dict[int, float] = {}
ACTIVE_TIMEOUT = 600  # 10 minutes


def bot_mentioned(text: str) -> bool:
    return f"@{BOT_USERNAME}" in text.lower()


def is_reply_to_bot(msg: dict) -> bool:
    """Check if message is a reply to a bot message."""
    reply = msg.get("reply_to_message")
    if not reply:
        return False
    return reply.get("from", {}).get("id") == BOT_ID


def is_active_user(user_id: int) -> bool:
    """Check if user has an active conversation (bot asked a question recently)."""
    expiry = active_users.get(user_id)
    if expiry and time.time() < expiry:
        return True
    active_users.pop(user_id, None)
    return False


def mark_user_active(user_id: int):
    """Mark user as having an active conversation."""
    active_users[user_id] = time.time() + ACTIVE_TIMEOUT


async def send_to_agent(text: str) -> str:
    """Send message to Base44 agent, return agent's reply."""
    url = f"{BASE44_BASE}/conversations/{CONV_ID}/messages"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            headers={"api_key": BASE44_API_KEY, "Content-Type": "application/json"},
            json={"content": text, "role": "user"},
        )
        print(f"[base44] {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            return data.get("content", "")
    return ""


async def send_telegram(chat_id: int, text: str, thread_id: Optional[int] = None):
    """Send message back to Telegram chat."""
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if thread_id:
        payload["message_thread_id"] = thread_id
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{TG_API}/sendMessage", json=payload)
        print(f"[telegram] {resp.status_code}")


@app.get("/")
def health():
    return {"ok": True, "service": "turbota-webhook", "version": "4.0"}


@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = await request.json()
    except Exception:
        return Response(status_code=200)

    msg = update.get("message")
    if not msg:
        return Response(status_code=200)

    if msg.get("from", {}).get("is_bot"):
        return Response(status_code=200)

    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    chat_type = chat.get("type", "")
    text = (msg.get("text") or msg.get("caption") or "").strip()

    if not text:
        return Response(status_code=200)

    from_user = msg.get("from", {})
    user_id = from_user.get("id", 0)
    username = from_user.get("username") or f"{from_user.get('first_name', '')} {from_user.get('last_name', '')}".strip()
    thread_id = msg.get("message_thread_id")

    # --- GROUP ---
    if chat_id == GROUP_CHAT_ID:
        # Accept if: bot tagged, OR reply to bot message, OR user has active conversation
        should_process = bot_mentioned(text) or is_reply_to_bot(msg) or is_active_user(user_id)

        if not should_process:
            return Response(status_code=200)

        prompt = (
            f"[ГРУПА ОБЛІК] Від: {username} | Тред: {thread_id or 'загальний'}\n"
            f"{text}"
        )
        print(f"[group] from={username} thread={thread_id} text={text[:80]}")
        reply = await send_to_agent(prompt)
        if reply:
            await send_telegram(chat_id, reply, thread_id)
            # Bot replied = conversation active, listen for follow-ups
            mark_user_active(user_id)
        return Response(status_code=200)

    # --- PRIVATE: forward all messages ---
    if chat_type == "private":
        prompt = f"[ПРИВАТНЕ] Від: {username}\n{text}"
        print(f"[private] from={username} text={text[:80]}")
        reply = await send_to_agent(prompt)
        if reply:
            await send_telegram(chat_id, reply)
        return Response(status_code=200)

    return Response(status_code=200)
