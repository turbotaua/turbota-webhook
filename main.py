import os
from typing import Optional
import httpx
from fastapi import FastAPI, Request, Response

app = FastAPI()

# --- Config ---
GROUP_CHAT_ID = -1001866962075
BOT_USERNAME = "turbotaautomationbot"
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8662984452:AAGp7Ewudyv-kMRtmeiKdnv7iZD9mohpV9s")
BASE44_BASE = "https://app.base44.com/api/agents/69cfa85cc1cb5d9be0b98f3c"
BASE44_API_KEY = os.environ.get("BASE44_API_KEY", "cc98d8b4eca243de93f5eb9fd8b57d88")
CONV_ID = os.environ.get("BASE44_CONV_ID", "69cfa85e6e1663b653e71819")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def bot_mentioned(text: str) -> bool:
    return f"@{BOT_USERNAME}" in text.lower()


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
    return {"ok": True, "service": "turbota-webhook", "version": "3.1"}


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
    username = from_user.get("username") or f"{from_user.get('first_name', '')} {from_user.get('last_name', '')}".strip()
    thread_id = msg.get("message_thread_id")

    # --- GROUP: only react when bot is tagged ---
    if chat_id == GROUP_CHAT_ID:
        if not bot_mentioned(text):
            return Response(status_code=200)

        prompt = (
            f"[ГРУПА ОБЛІК] Від: {username} | Тред: {thread_id or 'загальний'}\n"
            f"{text}"
        )
        print(f"[group] from={username} thread={thread_id} text={clean_text[:80]}")
        reply = await send_to_agent(prompt)
        if reply:
            await send_telegram(chat_id, reply, thread_id)
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
