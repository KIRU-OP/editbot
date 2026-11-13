import asyncio
import re
from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import ChatPermissions

from config import API_ID, API_HASH, BOT_TOKEN, OWNER_IDS, DEFAULT_MUTE_MINUTES, CHANNEL_SCAN_POSTS, LOG_CHAT_ID, PROFILE_CACHE_SECONDS
from database import connect_db, db, group_settings, log_action

app = Client("editbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

INVITE_RE = re.compile(r"(?i)(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)[A-Za-z0-9_-]+")
PUBLIC_TG_RE = re.compile(r"(?i)(?:https?://)?(?:www\.)?t\.me/([A-Za-z][A-Za-z0-9_]{3,})")
USERNAME_RE = re.compile(r"(?<!\w)@([A-Za-z][A-Za-z0-9_]{3,})")
PROFILE_CACHE = {}
CACHE_LOCK = asyncio.Lock()


def message_text(message):
    return " ".join(filter(None, [message.text or "", message.caption or ""]))


def extract_group_invites(text):
    return sorted(set(m.group(0).rstrip(".,!?)") for m in INVITE_RE.finditer(text or "")))


def extract_public_handles(text):
    handles = {m.group(1) for m in PUBLIC_TG_RE.finditer(text or "")}
    handles.update(m.group(1) for m in USERNAME_RE.finditer(text or ""))
    return handles


async def is_admin(client, chat_id, user_id):
    if user_id in OWNER_IDS:
        return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except Exception:
        return False


async def is_approved(chat_id, user_id):
    return await db().approved_users.find_one({"chat_id": chat_id, "user_id": user_id}) is not None


async def is_link_approved(chat_id, link):
    normalized = link.rstrip("/").lower()
    return await db().approved_links.find_one({"chat_id": chat_id, "link": normalized}) is not None


async def inspect_profile_and_public_channel(client, user_id):
    """Inspect only profile/channel information Telegram exposes to this bot."""
    now = datetime.now(timezone.utc).timestamp()
    async with CACHE_LOCK:
        cached = PROFILE_CACHE.get(user_id)
        if cached and now - cached[0] < PROFILE_CACHE_SECONDS:
            return cached[1]

    findings = []
    handles = set()
    try:
        profile = await client.get_chat(user_id)
        bio = getattr(profile, "bio", None) or ""
        links = extract_group_invites(bio)
        if links:
            findings.append(("profile bio contains a group invite", links[0]))
        handles = extract_public_handles(bio)
    except Exception:
        # An inaccessible profile is not treated as a violation.
        pass

    # Inspect public channel handles explicitly visible in accessible profile text.
    for handle in list(handles)[:3]:
        try:
            channel = await client.get_chat(handle)
            async for post in client.get_chat_history(channel.id, limit=CHANNEL_SCAN_POSTS):
                links = extract_group_invites(message_text(post))
                if links:
                    findings.append((f"public channel @{handle} contains a group invite", links[0]))
                    break
        except Exception:
            continue

    async with CACHE_LOCK:
        PROFILE_CACHE[user_id] = (now, findings)
    return findings


async def mute_member(client, chat_id, user, reason, minutes):
    until = None if minutes <= 0 else datetime.now(timezone.utc) + timedelta(minutes=minutes)
    await client.restrict_chat_member(chat_id, user.id, ChatPermissions(can_send_messages=False), until_date=until)
    label = "@" + user.username if user.username else (user.first_name or str(user.id))
    await log_action(chat_id, user.id, label, reason, "AUTO-MUTE")
    return label


async def notify_log(client, chat_id, user, reason, label):
    if not LOG_CHAT_ID:
        return
    try:
        await client.send_message(LOG_CHAT_ID, (
            "🛡️ EDITBOT | Anti-Promo Action\n"
            f"Group: {chat_id}\nUser: {label} ({user.id})\nReason: {reason}"
        ))
    except Exception:
        pass


@app.on_message(filters.group & ~filters.service & ~filters.command(
    ["antipromo", "approve", "unapprove", "approvedusers", "approve_link", "unapprove_link", "approved_links", "unmute", "promologs", "scan"]
))
async def anti_promo_handler(client, message):
    user = message.from_user
    if not user or user.is_bot:
        return
    settings = await group_settings(message.chat.id)
    if not settings.get("antipromo", False):
        return
    if await is_admin(client, message.chat.id, user.id) or await is_approved(message.chat.id, user.id):
        return

    reason = None
    direct_links = extract_group_invites(message_text(message))
    if direct_links and settings.get("scan_message_links", True):
        blocked_links = [link for link in direct_links if not await is_link_approved(message.chat.id, link)]
        if blocked_links:
            reason = "unapproved group invite link posted in a group message"
    else:
        findings = await inspect_profile_and_public_channel(client, user.id)
        if findings:
            reason = findings[0][0]
    if not reason:
        return

    minutes = int(settings.get("mute_minutes", DEFAULT_MUTE_MINUTES))
    try:
        label = await mute_member(client, message.chat.id, user, reason, minutes)
        duration = "until an admin unmutes" if minutes <= 0 else f"{minutes} minutes"
        await message.reply_text(
            "🛡️ EDITBOT Anti-Promotion\n"
            f"Member: {label}\nReason: {reason}\nAction: Muted for {duration}."
        )
        await notify_log(client, message.chat.id, user, reason, label)
    except Exception as exc:
        await log_action(message.chat.id, user.id, user.username or str(user.id), reason,
                         "MUTE_FAILED: " + type(exc).__name__)


async def require_admin(message):
    if not message.from_user or not await is_admin(app, message.chat.id, message.from_user.id):
        await message.reply_text("⛔ This command is available to group admins only.")
        return False
    return True


@app.on_message(filters.group & filters.command("antipromo"))
async def antipromo_command(client, message):
    if not await require_admin(message):
        return
    args = message.command[1:] if len(message.command) > 1 else []
    if not args or args[0].lower() not in ("on", "off", "enable", "disable", "status"):
        return await message.reply_text(
            "Anti-Promo Control\n"
            "/antipromo on — enable scanning\n"
            "/antipromo off — disable scanning\n"
            "/antipromo status — show current state"
        )
    action = args[0].lower()
    current = await group_settings(message.chat.id)
    if action in ("on", "enable", "off", "disable"):
        enabled = action in ("on", "enable")
        await db().groups.update_one({"chat_id": message.chat.id}, {"$set": {"antipromo": enabled}}, upsert=True)
        return await message.reply_text("✅ Anti-Promo scanning " + ("enabled." if enabled else "disabled."))
    return await message.reply_text(
        f"Anti-Promo: {'ON' if current.get('antipromo') else 'OFF'}\n"
        f"Mute duration: {current.get('mute_minutes', DEFAULT_MUTE_MINUTES)} minutes"
    )


async def resolve_target(client, message):
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user
    if len(message.command) > 1:
        try:
            return await client.get_users(message.command[1])
        except Exception:
            return None
    return None


@app.on_message(filters.group & filters.command("approve"))
async def approve_command(client, message):
    if not await require_admin(message):
        return
    target = await resolve_target(client, message)
    if not target:
        return await message.reply_text("Reply to a user or use /approve @username.")
    await db().approved_users.update_one(
        {"chat_id": message.chat.id, "user_id": target.id},
        {"$set": {"username": target.username, "approved_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    await message.reply_text(f"✅ Approved {target.mention} for this group.")


@app.on_message(filters.group & filters.command("unapprove"))
async def unapprove_command(client, message):
    if not await require_admin(message):
        return
    target = await resolve_target(client, message)
    if not target:
        return await message.reply_text("Reply to a user or use /unapprove @username.")
    await db().approved_users.delete_one({"chat_id": message.chat.id, "user_id": target.id})
    await message.reply_text(f"✅ Removed {target.mention} from the approved list.")


@app.on_message(filters.group & filters.command("approvedusers"))
async def approved_users_command(client, message):
    if not await require_admin(message):
        return
    rows = await db().approved_users.find({"chat_id": message.chat.id}).limit(100).to_list(length=100)
    if not rows:
        return await message.reply_text("No approved users in this group.")
    lines = [f"• {row['user_id']} — @{row.get('username') or 'no username'}" for row in rows]
    await message.reply_text("Approved Users\n" + "\n".join(lines))


@app.on_message(filters.group & filters.command("unmute"))
async def unmute_command(client, message):
    if not await require_admin(message):
        return
    target = await resolve_target(client, message)
    if not target:
        return await message.reply_text("Reply to a user or use /unmute @username.")
    await client.restrict_chat_member(
        message.chat.id, target.id,
        ChatPermissions(can_send_messages=True, can_send_media_messages=True,
                        can_send_other_messages=True, can_add_web_page_previews=True),
    )
    await message.reply_text(f"🔊 {target.mention} has been unmuted.")


@app.on_message(filters.group & filters.command("promologs"))
async def promologs_command(client, message):
    if not await require_admin(message):
        return
    rows = await db().moderation_logs.find({"chat_id": message.chat.id}).sort("created_at", -1).limit(10).to_list(length=10)
    if not rows:
        return await message.reply_text("No anti-promo actions recorded yet.")
    lines = [f"• {row['user_id']} — {row['action']} — {row['reason']}" for row in rows]
    await message.reply_text("Recent Anti-Promo Logs\n" + "\n".join(lines))


@app.on_message(filters.group & filters.command("scan"))
async def scan_command(client, message):
    if not await require_admin(message):
        return
    target = await resolve_target(client, message)
    if not target:
        return await message.reply_text("Reply to a member or use /scan @username.")
    findings = await inspect_profile_and_public_channel(client, target.id)
    if findings:
        return await message.reply_text("Scan findings\n" + "\n".join(
            f"• {reason}: {link}" for reason, link in findings
        ))
    await message.reply_text(
        "No accessible profile/channel promotion found. Telegram may hide profile or channel "
        "details from bots, so this result cannot guarantee that no promotion exists."
    )


@app.on_message(filters.group & filters.command("approve_link"))
async def approve_link_command(client, message):
    if not await require_admin(message):
        return
    if len(message.command) < 2:
        return await message.reply_text("Usage: /approve_link https://t.me/+invite")
    link = message.command[1].rstrip("/").lower()
    if not extract_group_invites(link):
        return await message.reply_text("Please provide a Telegram invite link (t.me/+... or t.me/joinchat/...).")
    await db().approved_links.update_one(
        {"chat_id": message.chat.id, "link": link},
        {"$set": {"added_by": message.from_user.id, "added_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    await message.reply_text("✅ This invite link is now approved for this group.")


@app.on_message(filters.group & filters.command("unapprove_link"))
async def unapprove_link_command(client, message):
    if not await require_admin(message):
        return
    if len(message.command) < 2:
        return await message.reply_text("Usage: /unapprove_link https://t.me/+invite")
    link = message.command[1].rstrip("/").lower()
    result = await db().approved_links.delete_one({"chat_id": message.chat.id, "link": link})
    await message.reply_text("✅ Approved link removed." if result.deleted_count else "That link was not in the approved list.")


@app.on_message(filters.group & filters.command("approved_links"))
async def approved_links_command(client, message):
    if not await require_admin(message):
        return
    rows = await db().approved_links.find({"chat_id": message.chat.id}).limit(50).to_list(length=50)
    if not rows:
        return await message.reply_text("No approved invite links in this group.")
    await message.reply_text("Approved Invite Links\\n" + "\\n".join("• " + row["link"] for row in rows))


async def startup():
    await connect_db()
    print("EDITBOT connected to MongoDB.")

if __name__ == "__main__":
    app.run(startup)
