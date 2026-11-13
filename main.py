import asyncio
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton

from config import (
    API_ID, API_HASH, BOT_TOKEN, OWNER_IDS, DEFAULT_MUTE_MINUTES,
    CHANNEL_SCAN_POSTS, LOG_CHAT_ID, PROFILE_CACHE_SECONDS,
    FLOOD_LIMIT, FLOOD_WINDOW_SECONDS,
)
from database import connect_db, db, group_settings, log_action

app = Client("editbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

INVITE_RE = re.compile(r"(?i)(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)[A-Za-z0-9_-]+")
PUBLIC_TG_RE = re.compile(r"(?i)(?:https?://)?(?:www\.)?t\.me/([A-Za-z][A-Za-z0-9_]{3,})")
USERNAME_RE = re.compile(r"(?<![\w/])@([A-Za-z][A-Za-z0-9_]{3,})")
PROFILE_CACHE = {}
CACHE_LOCK = asyncio.Lock()
FLOOD_BUCKETS = defaultdict(deque)
START_TIME = time.monotonic()


def message_text(message):
    return " ".join(filter(None, [getattr(message, "text", None) or "", getattr(message, "caption", None) or ""]))


def extract_group_invites(value):
    return sorted(set(m.group(0).rstrip(".,!?)") for m in INVITE_RE.finditer(value or "")))


def extract_public_handles(value):
    handles = {m.group(1) for m in PUBLIC_TG_RE.finditer(value or "")}
    handles.update(m.group(1) for m in USERNAME_RE.finditer(value or ""))
    return handles


def normalize_link(link):
    return link.rstrip("/").lower()


async def is_admin(client, chat_id, user_id):
    if user_id in OWNER_IDS:
        return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except Exception:
        return False


async def require_admin(message):
    if not message.from_user or not await is_admin(app, message.chat.id, message.from_user.id):
        await message.reply_text("⛔ This command is available to group admins only.")
        return False
    return True


async def is_approved(chat_id, user_id):
    return await db().approved_users.find_one({"chat_id": chat_id, "user_id": user_id}) is not None


async def is_sudo(user_id):
    return user_id in OWNER_IDS or await db().sudo_users.find_one({"user_id": user_id}) is not None


async def require_owner(message):
    if not message.from_user or message.from_user.id not in OWNER_IDS:
        await message.reply_text("⛔ This command is reserved for the bot owner.")
        return False
    return True


def readable_uptime():
    seconds = int(time.monotonic() - START_TIME)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


async def is_link_approved(chat_id, link):
    return await db().approved_links.find_one({"chat_id": chat_id, "link": normalize_link(link)}) is not None


async def inspect_profile_and_public_channel(client, user_id, force=False):
    """Scan only profile/channel data Telegram exposes to this bot."""
    now = datetime.now(timezone.utc).timestamp()
    async with CACHE_LOCK:
        cached = PROFILE_CACHE.get(user_id)
        if not force and cached and now - cached[0] < PROFILE_CACHE_SECONDS:
            return cached[1]

    findings = []
    handles = set()
    try:
        profile = await client.get_chat(user_id)
        bio = getattr(profile, "bio", None) or ""
        bio_links = extract_group_invites(bio)
        if bio_links:
            findings.append(("member bio contains a Telegram group invite", bio_links[0]))
        handles = extract_public_handles(bio)
        for handle in sorted(handles)[:3]:
            try:
                linked_chat = await client.get_chat(handle)
                if linked_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                    findings.append((f"member bio links to public group @{handle}", f"https://t.me/{handle}"))
            except Exception:
                continue
    except Exception:
        # An inaccessible profile is not evidence of a violation.
        pass

    # A public channel is scanned only when its public handle is visible in accessible bio text.
    for handle in sorted(handles)[:3]:
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
    await client.restrict_chat_member(
        chat_id, user.id,
        ChatPermissions(can_send_messages=False),
        until_date=until,
    )
    label = "@" + user.username if user.username else (user.first_name or str(user.id))
    await log_action(chat_id, user.id, label, reason, "AUTO-MUTE")
    return label


async def notify_log(client, chat_id, user, reason, label, action="AUTO-MUTE"):
    target = LOG_CHAT_ID
    if not target:
        return
    try:
        await client.send_message(
            target,
            "🛡️ EDITBOT | Moderation Log\n"
            f"Group: {chat_id}\nUser: {label} ({user.id})\n"
            f"Action: {action}\nReason: {reason}",
        )
    except Exception:
        pass


async def handle_promo(client, message, settings):
    user = message.from_user
    if not user or user.is_bot:
        return
    if await is_admin(client, message.chat.id, user.id):
        return
    if await is_approved(message.chat.id, user.id):
        return

    reasons = []
    text_links = extract_group_invites(message_text(message))
    if settings.get("scan_message_links", True):
        for link in text_links:
            if not await is_link_approved(message.chat.id, link):
                reasons.append(("unapproved group invite posted in a message", link))
                break
        # Resolve public Telegram handles in messages: public groups are promo links,
        # while channels are not treated as group invites merely because they are linked.
        if not reasons:
            for handle in sorted(extract_public_handles(message_text(message)))[:3]:
                try:
                    linked_chat = await client.get_chat(handle)
                    if linked_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                        public_link = f"https://t.me/{handle}"
                        if not await is_link_approved(message.chat.id, public_link):
                            reasons.append(("public group link posted in a message", public_link))
                            break
                except Exception:
                    continue

    # Run profile/channel scan independently, even when the message itself contains a link.
    if settings.get("scan_bio", True) or settings.get("scan_public_channel_posts", True):
        findings = await inspect_profile_and_public_channel(client, user.id)
        for reason, link in findings:
            if not await is_link_approved(message.chat.id, link):
                reasons.append((reason, link))
                break

    if not reasons:
        return
    reason, _link = reasons[0]
    try:
        minutes = int(settings.get("mute_minutes", DEFAULT_MUTE_MINUTES))
        label = await mute_member(client, message.chat.id, user, reason, minutes)
        duration = "until an admin unmutes" if minutes <= 0 else f"{minutes} minutes"
        await message.reply_text(
            "🛡️ EDITBOT Anti-Promotion\n"
            f"Member: {label}\nReason: {reason}\n"
            f"Action: Muted for {duration}.",
        )
        await notify_log(client, message.chat.id, user, reason, label)
    except Exception as exc:
        await log_action(
            message.chat.id, user.id, user.username or str(user.id),
            reason, "MUTE_FAILED: " + type(exc).__name__,
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


@app.on_message(filters.group & ~filters.service & ~filters.edited)
async def group_message_handler(client, message):
    user = message.from_user
    if not user or user.is_bot:
        return
    # Keep a baseline so the original text can be compared when a message is edited.
    await db().message_snapshots.update_one(
        {"chat_id": message.chat.id, "message_id": message.id},
        {"$set": {
            "user_id": user.id,
            "text": message_text(message)[:4000],
            "updated_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )

    if message.text and message.text.startswith("/"):
        return
    settings = await group_settings(message.chat.id)
    if settings.get("antipromo", False):
        await handle_promo(client, message, settings)

    if settings.get("antiflood", False) and not await is_admin(client, message.chat.id, user.id):
        now = datetime.now(timezone.utc).timestamp()
        key = (message.chat.id, user.id)
        bucket = FLOOD_BUCKETS[key]
        bucket.append(now)
        while bucket and now - bucket[0] > FLOOD_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) > int(settings.get("flood_limit", FLOOD_LIMIT)):
            try:
                minutes = int(settings.get("flood_mute_minutes", 5))
                await mute_member(client, message.chat.id, user, "message flood", minutes)
                bucket.clear()
                await message.reply_text(f"🚦 Flood protection: {user.mention} was muted for {minutes} minutes.")
            except Exception:
                pass


@app.on_edited_message(filters.group)
async def edited_message_handler(client, message):
    user = message.from_user
    if not user or user.is_bot:
        return
    old = await db().message_snapshots.find_one(
        {"chat_id": message.chat.id, "message_id": message.id}
    )
    old_text = old.get("text", "") if old else "(original message unavailable)"
    new_text = message_text(message)[:4000]
    await db().edit_history.insert_one({
        "chat_id": message.chat.id,
        "message_id": message.id,
        "user_id": user.id,
        "username": user.username,
        "old_text": old_text,
        "new_text": new_text,
        "edited_at": datetime.now(timezone.utc),
    })
    await db().message_snapshots.update_one(
        {"chat_id": message.chat.id, "message_id": message.id},
        {"$set": {"user_id": user.id, "text": new_text, "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    settings = await group_settings(message.chat.id)
    # Edit deletion is intentionally OFF unless an admin enables it.
    if (settings.get("delete_edited_messages", False)
            and not await is_admin(client, message.chat.id, user.id)
            and not await is_sudo(user.id)):
        try:
            await message.delete()
            await log_action(message.chat.id, user.id, user.username or str(user.id),
                             "edited message removed by edit guard", "EDIT-DELETE")
            await client.send_message(
                message.chat.id,
                f"✏️ {user.mention} edited a message. The edited message was removed by EDITBOT."
            )
            await notify_log(
                client, message.chat.id, user, "edited message removed by edit guard",
                user.username or str(user.id), action="EDIT-DELETE"
            )
        except Exception as exc:
            await log_action(message.chat.id, user.id, user.username or str(user.id),
                             "edit deletion failed: " + type(exc).__name__, "EDIT-DELETE-FAILED")


@app.on_message(filters.group & filters.command("antipromo"))
async def antipromo_command(client, message):
    if not await require_admin(message):
        return
    args = message.command[1:] if len(message.command) > 1 else []
    if not args or args[0].lower() not in ("on", "off", "enable", "disable", "status"):
        return await message.reply_text(
            "🛡️ Anti-Promo Controls\n"
            "/antipromo on — enable checks\n"
            "/antipromo off — disable checks\n"
            "/antipromo status — show settings"
        )
    action = args[0].lower()
    current = await group_settings(message.chat.id)
    if action in ("on", "enable", "off", "disable"):
        enabled = action in ("on", "enable")
        await db().groups.update_one({"chat_id": message.chat.id},
                                     {"$set": {"antipromo": enabled}}, upsert=True)
        return await message.reply_text("✅ Anti-Promo " + ("enabled." if enabled else "disabled."))
    return await message.reply_text(
        f"Anti-Promo: {'ON' if current.get('antipromo') else 'OFF'}\n"
        f"Mute duration: {current.get('mute_minutes', DEFAULT_MUTE_MINUTES)} minutes\n"
        f"Bio scan: {'ON' if current.get('scan_bio', True) else 'OFF'}\n"
        f"Channel scan: {'ON' if current.get('scan_public_channel_posts', True) else 'OFF'}"
    )


@app.on_message(filters.group & filters.command("approve"))
async def approve_command(client, message):
    if not await require_admin(message):
        return
    target = await resolve_target(client, message)
    if not target:
        return await message.reply_text("Reply to a user or use /approve @username.")
    await db().approved_users.update_one(
        {"chat_id": message.chat.id, "user_id": target.id},
        {"$set": {"username": target.username, "approved_at": datetime.now(timezone.utc),
                  "approved_by": message.from_user.id}},
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


@app.on_message(filters.group & filters.command(["approved", "approvedusers"]))
async def approved_users_command(client, message):
    if not await require_admin(message):
        return
    rows = await db().approved_users.find({"chat_id": message.chat.id}).sort("approved_at", -1).limit(100).to_list(length=100)
    if not rows:
        return await message.reply_text("No approved users in this group.")
    lines = [f"• {row['user_id']} — @{row.get('username') or 'no username'}" for row in rows]
    await message.reply_text("✅ Approved Users\n" + "\n".join(lines))


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
    await log_action(message.chat.id, target.id, target.username or str(target.id),
                     "unmuted by admin", "UNMUTE")
    await message.reply_text(f"🔊 {target.mention} has been unmuted.")


@app.on_message(filters.group & filters.command("promologs"))
async def promologs_command(client, message):
    if not await require_admin(message):
        return
    rows = await db().moderation_logs.find({"chat_id": message.chat.id}).sort("created_at", -1).limit(15).to_list(length=15)
    if not rows:
        return await message.reply_text("No moderation actions recorded yet.")
    lines = [f"• {row.get('username') or row['user_id']} — {row['action']} — {row['reason']}" for row in rows]
    await message.reply_text("📋 Recent Moderation Logs\n" + "\n".join(lines))


@app.on_message(filters.group & filters.command("scan"))
async def scan_command(client, message):
    if not await require_admin(message):
        return
    target = await resolve_target(client, message)
    if not target:
        return await message.reply_text("Reply to a member or use /scan @username.")
    findings = await inspect_profile_and_public_channel(client, target.id, force=True)
    if findings:
        return await message.reply_text("🔎 Scan Findings\n" + "\n".join(
            f"• {reason}: {link}" for reason, link in findings
        ))
    await message.reply_text(
        "No promotion found in the profile/channel information accessible to this bot. "
        "Telegram may hide some profile or channel details; this is not a guarantee that none exists."
    )


@app.on_message(filters.group & filters.command("approve_link"))
async def approve_link_command(client, message):
    if not await require_admin(message):
        return
    if len(message.command) < 2:
        return await message.reply_text("Usage: /approve_link https://t.me/+invite")
    link = normalize_link(message.command[1])
    if not extract_group_invites(link):
        return await message.reply_text("Provide a Telegram group invite link (t.me/+... or t.me/joinchat/...).")
    await db().approved_links.update_one(
        {"chat_id": message.chat.id, "link": link},
        {"$set": {"added_by": message.from_user.id, "added_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    await message.reply_text("✅ Invite link approved for this group.")


@app.on_message(filters.group & filters.command("unapprove_link"))
async def unapprove_link_command(client, message):
    if not await require_admin(message):
        return
    if len(message.command) < 2:
        return await message.reply_text("Usage: /unapprove_link https://t.me/+invite")
    result = await db().approved_links.delete_one(
        {"chat_id": message.chat.id, "link": normalize_link(message.command[1])}
    )
    await message.reply_text("✅ Approved link removed." if result.deleted_count else "That link is not approved.")


@app.on_message(filters.group & filters.command("approved_links"))
async def approved_links_command(client, message):
    if not await require_admin(message):
        return
    rows = await db().approved_links.find({"chat_id": message.chat.id}).limit(50).to_list(length=50)
    if not rows:
        return await message.reply_text("No approved invite links in this group.")
    await message.reply_text("✅ Approved Invite Links\n" + "\n".join("• " + row["link"] for row in rows))


@app.on_message(filters.group & filters.command("antiflood"))
async def antiflood_command(client, message):
    if not await require_admin(message):
        return
    args = message.command[1:] if len(message.command) > 1 else []
    if not args or args[0].lower() not in ("on", "off", "status"):
        return await message.reply_text("/antiflood on | /antiflood off | /antiflood status")
    if args[0].lower() == "status":
        settings = await group_settings(message.chat.id)
        return await message.reply_text(f"Anti-Flood: {'ON' if settings.get('antiflood') else 'OFF'}")
    enabled = args[0].lower() == "on"
    await db().groups.update_one({"chat_id": message.chat.id},
                                 {"$set": {"antiflood": enabled}}, upsert=True)
    await message.reply_text("✅ Anti-Flood " + ("enabled." if enabled else "disabled."))


@app.on_message(filters.group & filters.command("editguard"))
async def editguard_command(client, message):
    if not await require_admin(message):
        return
    args = message.command[1:] if len(message.command) > 1 else []
    if not args or args[0].lower() not in ("on", "off", "status"):
        return await message.reply_text(
            "/editguard on — delete edited messages from non-admins\n"
            "/editguard off — keep edited messages (default)\n"
            "/editguard status"
        )
    if args[0].lower() == "status":
        settings = await group_settings(message.chat.id)
        return await message.reply_text(
            f"Edit deletion: {'ON' if settings.get('delete_edited_messages', False) else 'OFF'}"
        )
    enabled = args[0].lower() == "on"
    await db().groups.update_one({"chat_id": message.chat.id},
                                 {"$set": {"delete_edited_messages": enabled}}, upsert=True)
    await message.reply_text("✅ Edit deletion " + ("enabled." if enabled else "disabled."))


@app.on_message(filters.group & filters.command("editlogs"))
async def editlogs_command(client, message):
    if not await require_admin(message):
        return
    rows = await db().edit_history.find({"chat_id": message.chat.id}).sort("edited_at", -1).limit(5).to_list(length=5)
    if not rows:
        return await message.reply_text("No edited messages recorded yet.")
    lines = []
    for row in rows:
        lines.append(
            f"User: {row.get('username') or row['user_id']} | Message: {row['message_id']}\n"
            f"Before: {row.get('old_text', '')[:180]}\nAfter: {row.get('new_text', '')[:180]}"
        )
    await message.reply_text("📝 Recent Edit History\n\n" + "\n\n".join(lines))


@app.on_message(filters.group & filters.command("setmute"))
async def setmute_command(client, message):
    if not await require_admin(message):
        return
    if len(message.command) < 2 or not message.command[1].isdigit():
        return await message.reply_text("Usage: /setmute minutes (0 = until admin unmutes)")
    minutes = int(message.command[1])
    if minutes < 0 or minutes > 10080:
        return await message.reply_text("Choose a duration from 0 to 10080 minutes.")
    await db().groups.update_one({"chat_id": message.chat.id},
                                 {"$set": {"mute_minutes": minutes}}, upsert=True)
    await message.reply_text(f"✅ Anti-promo mute duration set to {minutes} minutes.")


@app.on_message(filters.group & filters.command("stats"))
async def stats_command(client, message):
    if not await require_admin(message):
        return
    chat_id = message.chat.id
    total_logs = await db().moderation_logs.count_documents({"chat_id": chat_id})
    approved = await db().approved_users.count_documents({"chat_id": chat_id})
    edits = await db().edit_history.count_documents({"chat_id": chat_id})
    settings = await group_settings(chat_id)
    await message.reply_text(
        "📊 EDITBOT Group Stats\n"
        f"Moderation actions: {total_logs}\nApproved members: {approved}\n"
        f"Edited messages tracked: {edits}\n"
        f"Anti-Promo: {'ON' if settings.get('antipromo') else 'OFF'}\n"
        f"Anti-Flood: {'ON' if settings.get('antiflood') else 'OFF'}"
    )




@app.on_message(filters.private & filters.command("start"))
@app.on_message(filters.group & filters.command("start"))
async def start_command(client, message):
    if message.chat.type == ChatType.PRIVATE:
        await message.reply_text(
            "👋 Welcome to EDITBOT!\n\n"
            "I help group admins manage edited messages, anti-promotion, approvals, "
            "flood protection and moderation logs.\n\n"
            "Add me to your group as an admin, grant message deletion/restrict-member "
            "permissions as needed, then use /help."
        )
    else:
        await message.reply_text(f"EDITBOT is online. Uptime: {readable_uptime()}\nUse /help to see commands.")


@app.on_message(filters.private & filters.command("help"))
@app.on_message(filters.group & filters.command("help"))
async def help_command(client, message):
    text = (
        "🛡️ EDITBOT COMMANDS\n\n"
        "GROUP ADMIN COMMANDS\n"
        "/antipromo on|off|status — promotion scanner\n"
        "/approve @user — approve a member\n"
        "/unapprove @user — revoke approval\n"
        "/approved — list approved members\n"
        "/unmute @user — unmute a member\n"
        "/scan @user — scan accessible profile/public channel data\n"
        "/promologs — recent moderation actions\n"
        "/approve_link <invite> — allow an invite\n"
        "/unapprove_link <invite> — remove allowed invite\n"
        "/approved_links — list allowed invites\n"
        "/antiflood on|off|status — flood protection\n"
        "/editguard on|off|status — edited-message deletion\n"
        "/editlogs — recent edit history\n"
        "/setmute <minutes> — set anti-promo mute duration\n"
        "/stats — current group statistics\n"
        "/id — show Telegram IDs\n\n"
        "OWNER COMMANDS\n"
        "/addsudo @user — grant sudo access\n"
        "/delsudo @user — revoke sudo access\n"
        "/sudolist — list sudo users\n"
        "/botstats — bot-wide statistics\n"
        "/status — bot uptime and status"
    )
    await message.reply_text(text)


@app.on_message(filters.private & filters.command("status"))
@app.on_message(filters.group & filters.command("status"))
async def status_command(client, message):
    await message.reply_text(
        "🟢 EDITBOT STATUS\n"
        f"Uptime: {readable_uptime()}\n"
        f"Mode: Pyrogram + MongoDB\n"
        f"Chat: {message.chat.id}"
    )


@app.on_message(filters.private & filters.command("id"))
@app.on_message(filters.group & filters.command("id"))
async def id_command(client, message):
    lines = [
        f"Your ID: {message.from_user.id if message.from_user else 'Unavailable'}",
        f"Chat ID: {message.chat.id}",
        f"Message ID: {message.id}",
    ]
    if len(message.command) > 1:
        try:
            target = await client.get_users(message.command[1])
            lines.append(f"User ID: {target.id}")
        except Exception:
            return await message.reply_text("I couldn't resolve that user. Try a valid @username or numeric ID.")
    if message.reply_to_message:
        reply = message.reply_to_message
        lines.append(f"Replied Message ID: {reply.id}")
        if reply.from_user:
            lines.append(f"Replied User ID: {reply.from_user.id}")
        elif reply.sender_chat:
            lines.append(f"Replied Sender Chat ID: {reply.sender_chat.id}")
    await message.reply_text("🆔 TELEGRAM IDs\n" + "\n".join(lines))


@app.on_message(filters.private & filters.command("addsudo"))
@app.on_message(filters.group & filters.command("addsudo"))
async def addsudo_command(client, message):
    if not await require_owner(message):
        return
    target = await resolve_target(client, message)
    if not target:
        return await message.reply_text("Reply to a user or use /addsudo @username.")
    if target.id in OWNER_IDS:
        return await message.reply_text("That user is already configured as an owner.")
    await db().sudo_users.update_one(
        {"user_id": target.id},
        {"$set": {"username": target.username, "added_by": message.from_user.id,
                  "added_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    await message.reply_text(f"✅ {target.mention} has been added as a Sudo user.")


@app.on_message(filters.private & filters.command(["delsudo", "rmsudo"]))
@app.on_message(filters.group & filters.command(["delsudo", "rmsudo"]))
async def delsudo_command(client, message):
    if not await require_owner(message):
        return
    target = await resolve_target(client, message)
    if not target:
        return await message.reply_text("Reply to a user or use /delsudo @username.")
    result = await db().sudo_users.delete_one({"user_id": target.id})
    await message.reply_text(
        f"✅ Sudo access removed from {target.mention}."
        if result.deleted_count else "That user is not in the Sudo list."
    )


@app.on_message(filters.private & filters.command("sudolist"))
@app.on_message(filters.group & filters.command("sudolist"))
async def sudolist_command(client, message):
    if not await require_owner(message):
        return
    rows = await db().sudo_users.find({}).sort("added_at", 1).limit(100).to_list(length=100)
    lines = [f"• {row['user_id']} — @{row.get('username') or 'no username'}" for row in rows]
    owners = [f"• {uid} — owner" for uid in sorted(OWNER_IDS)]
    await message.reply_text("👑 OWNERS & SUDO USERS\n" + "\n".join(owners + lines))


@app.on_message(filters.private & filters.command(["botstats", "globalstats", "stats"]))

@app.on_message(filters.group & filters.command(["botstats", "globalstats"]))
async def botstats_command(client, message):
    if not await require_owner(message):
        return
    groups = await db().groups.count_documents({})
    users = await db().approved_users.distinct("user_id")
    actions = await db().moderation_logs.count_documents({})
    edits = await db().edit_history.count_documents({})
    sudo_count = await db().sudo_users.count_documents({})
    await message.reply_text(
        "📊 EDITBOT GLOBAL STATS\n"
        f"Configured groups: {groups}\n"
        f"Approved users: {len(users)}\n"
        f"Moderation actions: {actions}\n"
        f"Edited messages tracked: {edits}\n"
        f"Sudo users: {sudo_count}\n"
        f"Uptime: {readable_uptime()}"
    )


async def startup():
    await connect_db()
    print("EDITBOT connected to MongoDB and is ready.")


if __name__ == "__main__":
    app.run(startup)
