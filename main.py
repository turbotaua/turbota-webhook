import os
import json
import asyncio
import httpx
from fastapi import FastAPI, Request, Response

app = FastAPI()

CHAT_ID = -1001866962075
BOT_USERNAME = "turbotaautomationbot"
BASE44_APP_ID = "69cfa85cc1cb5d9be0b98f3c"
BASE44_STATE_ID = "69cfdcf642028d771740ad67"  # TelegramBotState record id

# This API key is used ONLY to read TelegramBotState (public read via api-key won't work,
# so we use the rotating JWT stored in env and refreshed by Base44 automation)
BASE44_API_KEY = os.environ.get("BASE44_API_KEY", "cc98d8b4eca243de93f5eb9fd8b57d88")

# JWT cache — populated at startup and refreshed every 30 min
_jwt_cache = {"token": os.environ.get("BASE44_JWT", ""), "fetched_at": 0}

BASE44_ENTITY_URL = f"https://base44.app/api/apps/{BASE44_APP_ID}/entities/TelegramProcessedMessage"
BASE44_STATE_URL  = f"https://base44.app/api/apps/{BASE44_APP_ID}/entities/TelegramBotState/{BASE44_STATE_ID}"

KEYWORDS = {
    "incoming":       ["надійшло", "прийшло", "від постачальника", "отримали", "закупка", "закупили", "нова поставка"],
    "sales":          ["відвантаження", "відправили", "продали", "накладна", "реалізація"],
    "production":     ["виготовили", "зробили", "партія", "виробництво", "відлили", "виробили"],
    "expense":        ["оплатили", "витрати", "платіж", "оплата", "заплатили"],
    "transfer":       ["перемістили", "передали", "зі складу", "комісіонеру"],
    "purchase_order": ["замовили у постачальника", "зробили замовлення", "оформили замовлення"],
}

def classify(text: str) -> str:
    lower = text.lower()
    for op, kws in KEYWORDS.items():
        if any(k in lower for k in kws):
            return op
    return "unclear"

def bot_mentioned(text: str) -> bool:
    return f"@{BOT_USERNAME}".lower() in text.lower()

async def get_jwt() -> str:
    """Read current JWT from Base44 TelegramBotState entity."""
    import time
    now = time.time()
    # Refresh every 25 minutes
    if _jwt_cache["token"] and (now - _jwt_cache["fetched_at"]) < 1500:
        return _jwt_cache["token"]
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                BASE44_STATE_URL,
                headers={"Authorization": f"Bearer {_jwt_cache['token']}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                token = data.get("value", "")
                if token:
                    _jwt_cache["token"] = token
                    _jwt_cache["fetched_at"] = now
                    print(f"[JWT] refreshed from Base44")
                    return token
    except Exception as e:
        print(f"[JWT] refresh failed: {e}")
    return _jwt_cache["token"]

@app.get("/")
def health():
    return {"ok": True, "service": "turbota-webhook"}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = await request.json()
    except Exception:
        return Response(status_code=200)

    msg = update.get("message")
    if not msg:
        return Response(status_code=200)

    if msg.get("chat", {}).get("id") != CHAT_ID:
        return Response(status_code=200)

    if msg.get("from", {}).get("is_bot"):
        return Response(status_code=200)

    text = (msg.get("text") or msg.get("caption") or "").strip()
    if not text or not bot_mentioned(text):
        return Response(status_code=200)

    message_id = msg.get("message_id")
    thread_id  = msg.get("message_thread_id")
    from_user  = msg.get("from", {})
    username   = from_user.get("username") or f"{from_user.get('first_name','')} {from_user.get('last_name','')}".strip()

    payload = {
        "update_id":      update.get("update_id"),
        "message_id":     message_id,
        "chat_id":        str(CHAT_ID),
        "thread_id":      thread_id,
        "thread_name":    "",
        "from_user":      username,
        "text":           text,
        "status":         "pending_draft",
        "operation_type": classify(text),
    }

    jwt = await get_jwt()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            BASE44_ENTITY_URL,
            headers={"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"},
            json=payload,
        )
        print(f"[Base44] {resp.status_code} msg_id={message_id} thread={thread_id} op={payload['operation_type']}")

    return Response(status_code=200)
