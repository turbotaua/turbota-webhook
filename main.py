"""
TURBOTA Telegram Webhook v4.2 — minimal, no asyncio tricks
"""
import os
import asyncio
import httpx
from fastapi import FastAPI, Request, Response

GROUP_CHAT_ID  = -1001866962075
BOT_USERNAME   = "turbotaautomationbot"
BOT_TOKEN      = os.environ["BOT_TOKEN"]
OWNER_CHAT_ID  = int(os.environ["OWNER_CHAT_ID"])
TG_API         = f"https://api.telegram.org/bot{BOT_TOKEN}"
BUFFER_SECONDS = 4

app = FastAPI()

# Buffer: key=(chat_id, thread_id, user_id) → {"entries": [], "task": Task|None}
_buffer: dict = {}


def bot_mentioned(text: str) -> bool:
    return f"@{BOT_USERNAME}".lower() in (text or "").lower()


@app.get("/")
async def health():
    return {"ok": True, "service": "turbota-webhook", "version": "4.2"}


@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = await request.json()
    except Exception:
        return Response(status_code=200)

    msg = update.get("message")
    if not msg:
        return Response(status_code=200)

    chat      = msg.get("chat", {})
    chat_id   = chat.get("id")
    chat_type = chat.get("type", "")
    text      = (msg.get("text") or msg.get("caption") or "").strip()
    from_user = msg.get("from", {})

    if from_user.get("is_bot"):
        return Response(status_code=200)

    should_forward = False
    if chat_type == "private":
        should_forward = True
    elif chat_id == GROUP_CHAT_ID and chat_type in ("group", "supergroup"):
        if bot_mentioned(text):
            should_forward = True

    if should_forward:
        files = await extract_files(msg)
        await buffer_and_schedule(update.get("update_id"), msg, files)

    return Response(status_code=200)


async def get_file_url(file_id: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{TG_API}/getFile", params={"file_id": file_id})
            fp = r.json()["result"]["file_path"]
            return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fp}"
    except Exception as e:
        return f"[error: {e}]"


async def extract_files(msg: dict) -> list:
    files = []
    doc = msg.get("document")
    if doc:
        url = await get_file_url(doc["file_id"])
        files.append({"name": doc.get("file_name", "file"), "mime": doc.get("mime_type", ""), "url": url})
    photos = msg.get("photo")
    if photos:
        photo = max(photos, key=lambda p: p.get("file_size", 0))
        url = await get_file_url(photo["file_id"])
        files.append({"name": "photo.jpg", "mime": "image/jpeg", "url": url})
    return files


async def buffer_and_schedule(update_id, msg: dict, files: list):
    from_user = msg.get("from", {})
    chat      = msg.get("chat", {})
    key = (chat.get("id"), msg.get("message_thread_id"), from_user.get("id"))

    if key not in _buffer:
        _buffer[key] = {"entries": [], "task": None}

    _buffer[key]["entries"].append({"update_id": update_id, "msg": msg, "files": files,
                                    "text": (msg.get("text") or msg.get("caption") or "").strip()})

    old_task = _buffer[key]["task"]
    if old_task and not old_task.done():
        old_task.cancel()

    _buffer[key]["task"] = asyncio.create_task(flush_after(key))


async def flush_after(key):
    await asyncio.sleep(BUFFER_SECONDS)
    data = _buffer.pop(key, None)
    if not data or not data["entries"]:
        return

    entries   = data["entries"]
    first_msg = entries[0]["msg"]
    from_user = first_msg.get("from", {})
    chat      = first_msg.get("chat", {})
    username  = from_user.get("username") or f"{from_user.get('first_name','')} {from_user.get('last_name','')}".strip()

    all_files = []
    texts     = []
    for e in entries:
        all_files.extend(e["files"])
        if e["text"] and e["text"] not in texts:
            texts.append(e["text"])

    relay = (
        f"📨 TG_RELAY\n"
        f"update_id: {entries[-1]['update_id']}\n"
        f"chat_id: {chat.get('id')}\n"
        f"chat_type: {chat.get('type')}\n"
        f"thread_id: {first_msg.get('message_thread_id')}\n"
        f"message_ids: {[e['msg']['message_id'] for e in entries]}\n"
        f"from: {username}\n"
        f"messages_count: {len(entries)}\n"
    )

    if all_files:
        relay += f"files_count: {len(all_files)}\n"
        for i, f in enumerate(all_files, 1):
            relay += f"📎 file_{i}: {f['name']} ({f['mime']})\n   url: {f['url']}\n"

    relay += "---\n"
    relay += "\n".join(texts) if texts else "(без тексту)"

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{TG_API}/sendMessage", json={"chat_id": OWNER_CHAT_ID, "text": relay})
        print(f"[relay] {r.status_code} | key={key} | entries={len(entries)} | files={len(all_files)}")
