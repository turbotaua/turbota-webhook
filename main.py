"""
TURBOTA Telegram Webhook v4.1 — file support + smart grouping
Fixed: asyncio background tasks compatible with uvicorn/Railway
"""
import os
import asyncio
import httpx
from fastapi import FastAPI, Request, Response
from contextlib import asynccontextmanager

GROUP_CHAT_ID = -1001866962075
BOT_USERNAME  = "turbotaautomationbot"
BOT_TOKEN     = os.environ["BOT_TOKEN"]
OWNER_CHAT_ID = int(os.environ["OWNER_CHAT_ID"])
TG_API        = f"https://api.telegram.org/bot{BOT_TOKEN}"
BUFFER_SECONDS = 4

# Buffer: key=(chat_id, thread_id, user_id) → {"entries": [...], "handle": TimerHandle}
_buffer: dict = {}
_loop: asyncio.AbstractEventLoop = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop
    _loop = asyncio.get_event_loop()
    yield

app = FastAPI(lifespan=lifespan)


def bot_mentioned(text: str) -> bool:
    return f"@{BOT_USERNAME}".lower() in (text or "").lower()


@app.get("/")
def health():
    return {"ok": True, "service": "turbota-webhook", "version": "4.1"}


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
        files = await extract_file_info(msg)
        await buffer_message(msg, update.get("update_id"), files)

    return Response(status_code=200)


async def get_file_url(file_id: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{TG_API}/getFile", params={"file_id": file_id})
            data = r.json()
            if data.get("ok"):
                file_path = data["result"]["file_path"]
                return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    except Exception as e:
        print(f"[get_file_url] error: {e}")
    return None


async def extract_file_info(msg: dict) -> list[dict]:
    files = []

    doc = msg.get("document")
    if doc:
        url = await get_file_url(doc["file_id"])
        files.append({
            "name": doc.get("file_name", "file"),
            "mime": doc.get("mime_type", ""),
            "url": url or "[не вдалось отримати]"
        })

    photos = msg.get("photo")
    if photos:
        photo = sorted(photos, key=lambda p: p.get("file_size", 0), reverse=True)[0]
        url = await get_file_url(photo["file_id"])
        files.append({
            "name": "photo.jpg",
            "mime": "image/jpeg",
            "url": url or "[не вдалось отримати]"
        })

    return files


async def buffer_message(msg: dict, update_id, files: list):
    from_user = msg.get("from", {})
    chat      = msg.get("chat", {})
    user_id   = from_user.get("id")
    chat_id   = chat.get("id")
    thread_id = msg.get("message_thread_id")
    key       = (chat_id, thread_id, user_id)

    entry = {
        "update_id": update_id,
        "msg": msg,
        "files": files,
        "text": (msg.get("text") or msg.get("caption") or "").strip(),
    }

    if key not in _buffer:
        _buffer[key] = {"entries": [], "task": None}

    _buffer[key]["entries"].append(entry)

    # Cancel existing timer
    existing = _buffer[key].get("task")
    if existing and not existing.done():
        existing.cancel()

    # Schedule flush
    task = asyncio.create_task(flush_after_delay(key))
    _buffer[key]["task"] = task


async def flush_after_delay(key):
    try:
        await asyncio.sleep(BUFFER_SECONDS)
        await flush_buffer(key)
    except asyncio.CancelledError:
        pass


async def flush_buffer(key):
    if key not in _buffer:
        return

    data    = _buffer.pop(key)
    entries = data["entries"]
    if not entries:
        return

    first     = entries[0]["msg"]
    from_user = first.get("from", {})
    chat      = first.get("chat", {})
    username  = (
        from_user.get("username")
        or f"{from_user.get('first_name', '')} {from_user.get('last_name', '')}".strip()
    )
    chat_id   = chat.get("id")
    chat_type = chat.get("type")
    thread_id = first.get("message_thread_id")

    texts = []
    for e in entries:
        if e["text"] and e["text"] not in texts:
            texts.append(e["text"])

    all_files = []
    for e in entries:
        all_files.extend(e["files"])

    msg_ids = [e["msg"]["message_id"] for e in entries]

    relay = (
        f"📨 TG_RELAY\n"
        f"update_id: {entries[-1]['update_id']}\n"
        f"chat_id: {chat_id}\n"
        f"chat_type: {chat_type}\n"
        f"thread_id: {thread_id}\n"
        f"message_ids: {msg_ids}\n"
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
        r = await client.post(
            f"{TG_API}/sendMessage",
            json={"chat_id": OWNER_CHAT_ID, "text": relay},
        )
        print(f"[flush] status={r.status_code} key={key} entries={len(entries)} files={len(all_files)}")
        if r.status_code != 200:
            print(f"[flush] error: {r.text[:300]}")
