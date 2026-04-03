import os
from typing import Optional
import httpx
from fastapi import FastAPI, Request, Response

app = FastAPI()

# --- Config ---
GROUP_CHAT_ID = -1001866962075
BOT_USERNAME = "turbotaautomationbot"
BASE44_BASE = "https://app.base44.com/api/agents/69cfa85cc1cb5d9be0b98f3c"
BASE44_API_KEY = os.environ.get("BASE44_API_KEY", "cc98d8b4eca243de93f5eb9fd8b57d88")
CONV_ID = os.environ.get("BASE44_CONV_ID", "69cfa85e6e1663b653e71819")


def bot_mentioned(text: str) -> bool:
    return f"@{BOT_USERNAME}" in text.lower()


async def send_to_agent(text: str, metadata: Optional[dict] = None):
    """Send a message to Base44 agent via REST API."""
    url = f"{BASE44_BASE}/conversations/{CONV_ID}/messages"
    body = {"content": text, "role": "user"}
    if metadata:
        body["metadata"] = metadata
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            url,
            headers={"api_key": BASE44_API_KEY, "Content-Type": "application/json"},
            json=body,
        )
        print(f"[base44] {resp.status_code} len={len(resp.text)}")
        return resp


@app.get("/")
def health():
    return {"ok": True, "service": "turbota-webhook", "version": "2.0"}


@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = await request.json()
    except Exception:
        return Response(status_code=200)

    msg = update.get("message")
    if not msg:
        return Response(status_code=200)

    # Ignore bot messages
    if msg.get("from", {}).get("is_bot"):
        return Response(status_code=200)

    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    chat_type = chat.get("type", "")  # "private", "group", "supergroup"
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

        clean_text = text.replace(f"@{BOT_USERNAME}", "").strip()
        prompt = (
            f"[TELEGRAM ГРУПА ОБЛІК]\n"
            f"Від: {username}\n"
            f"Тред: {thread_id or 'загальний'}\n"
            f"Chat ID: {chat_id}\n"
            f"Message ID: {msg.get('message_id')}\n"
            f"---\n"
            f"{clean_text}"
        )
        print(f"[group] from={username} thread={thread_id} text={clean_text[:80]}")
        await send_to_agent(prompt)
        return Response(status_code=200)

    # --- PRIVATE: forward all messages ---
    if chat_type == "private":
        prompt = (
            f"[TELEGRAM ПРИВАТНЕ]\n"
            f"Від: {username} (chat_id: {chat_id})\n"
            f"---\n"
            f"{text}"
        )
        print(f"[private] from={username} text={text[:80]}")
        await send_to_agent(prompt)
        return Response(status_code=200)

    # --- Other chats: ignore ---
    return Response(status_code=200)
