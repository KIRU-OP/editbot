# EDITBOT — Telegram Group Moderation & Edit History

EDITBOT is a Pyrogram + MongoDB group moderation bot with anti-promotion scanning, admin approvals, flood protection, and message edit history.

## Main features

- Detect Telegram group invite links in group messages.
- Check a sender's accessible bio and scan public channel posts when a public channel handle is visible in that bio.
- Run profile/channel checks on ordinary messages too, not only messages containing links.
- Approved users and group admins are exempt from automatic moderation.
- Approve/unapprove members and invite links separately for each group.
- Anti-promo mute duration is configurable per group.
- Anti-flood protection with a configurable threshold.
- Record edited-message history (old text and new text).
- Optional edit deletion via /editguard; it is OFF by default.
- Notify the group when an edited message is removed.
- Owner-managed persistent Sudo users with /addsudo, /delsudo, and /sudolist.
- Telegram ID lookup, /start, /help, /status, and owner-only global statistics.
- Per-group settings, moderation logs, and basic statistics.
- Optional central moderation log chat via LOG_CHAT_ID.
- MongoDB indexes for group settings, approvals, snapshots, and moderation history.

## Telegram privacy and permission limits

A bot cannot force-open every member's private profile, private channel, or hidden linked-channel information. Telegram only returns information that the bot is permitted to access. EDITBOT scans accessible bio text and public channels whose handles are visible there. Inaccessible information is treated as unavailable, never as proof of a violation. There is no privacy bypass.

For automatic muting, add the bot as a group administrator and grant permission to restrict members. For channel scanning, the channel must be publicly accessible to the bot.

## Setup

1. Create a bot with BotFather.
2. Get API_ID and API_HASH from my.telegram.org.
3. Create a MongoDB database and URI.
4. Copy .env.example to .env and fill in your own values.
5. Install dependencies: `pip install -r requirements.txt`
6. Start: `python main.py`
7. Add the bot to your group as an administrator with permission to restrict members.
8. Enable desired features with the commands below.

## Admin commands

| Command | Purpose |
|---|---|
| `/antipromo on` | Enable anti-promotion scanning |
| `/antipromo off` | Disable anti-promotion scanning |
| `/antipromo status` | Show anti-promo settings |
| `/approve @user` | Approve a member (or reply to them) |
| `/unapprove @user` | Remove member approval |
| `/approved` | List approved members |
| `/approvedusers` | Backward-compatible alias |
| `/approve_link <invite>` | Approve one invite link |
| `/unapprove_link <invite>` | Remove an approved invite link |
| `/approved_links` | List approved invite links |
| `/scan @user` | Scan accessible bio/public-channel information |
| `/unmute @user` | Restore a member's send permissions |
| `/promologs` | Show recent moderation actions |
| `/setmute <minutes>` | Set anti-promo mute duration; 0 means manual unmute |
| `/antiflood on/off/status` | Control flood protection |
| `/editguard on/off/status` | Toggle deletion of edited messages |
| `/editlogs` | Show recent edit history |
| `/stats` | Show group moderation statistics |
| `/id [@user]` | Show user, chat, message, and replied-message IDs |
| `/start` | Start EDITBOT and show its introduction |
| `/help` | Show available commands |
| `/status` | Show bot uptime and status |
| `/addsudo @user` | Owner-only: grant Sudo privileges |
| `/delsudo @user` | Owner-only: revoke Sudo privileges |
| `/sudolist` | Owner-only: list owners and Sudo users |
| `/botstats` | Owner-only: global bot statistics |

Commands that target a user also accept a reply to that user's message. Group moderation commands are admin-only (OWNER_IDS is also recognized). Sudo management and global statistics are owner-only. Sudo users are exempt from edited-message deletion.

## Environment variables

See .env.example. Keep `.env` private and never commit bot tokens, API credentials, or database credentials.

## Safe defaults

- Anti-promo is OFF until an admin enables it.
- Anti-flood is OFF until an admin enables it.
- Edited-message deletion is OFF; edit history is still recorded.
- Only configured owners can add or remove Sudo users.
- Sudo users and group admins are exempt from edit deletion.
- Bio/channel scanning respects Telegram's access controls.
