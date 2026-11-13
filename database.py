from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, DB_NAME

_client = None
_db = None

async def connect_db():
    global _client, _db
    if not MONGO_URI:
        raise RuntimeError("MONGO_URI is required.")
    _client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    await _client.admin.command("ping")
    _db = _client[DB_NAME]
    await _db.groups.create_index("chat_id", unique=True)
    await _db.approved_users.create_index([("chat_id", 1), ("user_id", 1)], unique=True)
    await _db.approved_links.create_index([("chat_id", 1), ("link", 1)], unique=True)
    await _db.moderation_logs.create_index([("chat_id", 1), ("created_at", -1)])
    return _db

def db():
    if _db is None:
        raise RuntimeError("Database is not connected.")
    return _db

async def group_settings(chat_id: int):
    defaults = {
        "chat_id": chat_id,
        "antipromo": False,
        "mute_minutes": 60,
        "scan_bio": True,
        "scan_message_links": True,
        "scan_public_channel_posts": True,
    }
    await db().groups.update_one({"chat_id": chat_id}, {"$setOnInsert": defaults}, upsert=True)
    return await db().groups.find_one({"chat_id": chat_id})

async def log_action(chat_id: int, user_id: int, username: str, reason: str, action: str):
    await db().moderation_logs.insert_one({
        "chat_id": chat_id,
        "user_id": user_id,
        "username": username,
        "reason": reason,
        "action": action,
        "created_at": datetime.now(timezone.utc),
    })
