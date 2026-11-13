import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MONGO_URI = os.getenv("MONGO_URI", "")
DB_NAME = os.getenv("DB_NAME", "editbot")

OWNER_IDS = {
    int(value.strip())
    for value in os.getenv("OWNER_IDS", "").split(",")
    if value.strip().isdigit()
}

DEFAULT_MUTE_MINUTES = int(os.getenv("DEFAULT_MUTE_MINUTES", "60"))
CHANNEL_SCAN_POSTS = max(1, min(int(os.getenv("CHANNEL_SCAN_POSTS", "20")), 100))
PROFILE_CACHE_SECONDS = max(0, int(os.getenv("PROFILE_CACHE_SECONDS", "300")))
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID", "0") or "0")
FLOOD_LIMIT = max(2, int(os.getenv("FLOOD_LIMIT", "6")))
FLOOD_WINDOW_SECONDS = max(2, int(os.getenv("FLOOD_WINDOW_SECONDS", "8")))

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Set API_ID, API_HASH and BOT_TOKEN in your environment.")
