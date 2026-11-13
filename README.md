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
- Central activity log chat via LOG_CHAT_ID: bot startup, private /start events, bot added/removed from groups, and moderation events.
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

## Complete command guide

Send `/help` to EDITBOT in a private chat or in your group to see the full in-bot guide.

### Group admin commands

| Command | How to use it |
|---|---|
| `/antipromo on` | Enable promotion scanning in this group. |
| `/antipromo off` | Disable promotion scanning. |
| `/antipromo status` | View anti-promo and scan settings. |
| `/approve @username` | Exempt a member from anti-promo; alternatively reply to their message with `/approve`. |
| `/unapprove @username` | Remove a member's exemption; reply form also works. |
| `/approved` | List approved members. |
| `/approvedusers` | Alias for `/approved`. |
| `/unmute @username` | Restore a member's send permissions; reply form also works. |
| `/approve_link https://t.me/+CODE` | Add a group invite to this group's allowlist. |
| `/unapprove_link https://t.me/+CODE` | Remove an invite from the allowlist. |
| `/approved_links` | List allowed invite links. |
| `/scan @username` | Scan accessible bio/public-channel information; reply form also works. |
| `/promologs` | Show recent moderation actions. |
| `/antiflood on` / `off` / `status` | Enable, disable, or check flood protection. |
| `/editguard on` / `off` / `status` | Enable, disable, or check edited-message deletion. |
| `/editlogs` | Show recent before/after edit history. |
| `/setmute 30` | Set anti-promo mutes to 30 minutes. |
| `/setmute 0` | Keep auto-muted members muted until an admin unmutes them. |
| `/stats` | Show this group's moderation statistics. |
| `/id` | Show your Telegram ID, chat ID, and message ID. |
| `/id @username` | Look up a user's Telegram ID. |

### Owner-only commands

| Command | How to use it |
|---|---|
| `/addsudo @username` | Grant persistent Sudo access; you can also reply to the user's message with `/addsudo`. |
| `/delsudo @username` | Revoke Sudo access; reply form also works. |
| `/rmsudo @username` | Alias for `/delsudo`. |
| `/sudolist` | List configured owners and Sudo users. |
| `/botstats` | Show global bot statistics. |
| `/globalstats` | Alias for `/botstats`. |
| `/stats` in private chat | Show global statistics for the owner. |

### General commands

| Command | How to use it |
|---|---|
| `/start` | Show the welcome message and setup hint. |
| `/help` | Display the complete command guide inside Telegram. |
| `/status` | Show uptime and runtime information. |

### Quick setup in a group

1. Add EDITBOT to your group and promote it to administrator.
2. Grant message-deletion permission and restrict-members permission.
3. Run `/antipromo on` to enable promotion checks.
4. Optionally run `/antiflood on` and `/editguard on`.
5. Use `/help` whenever you need command syntax and usage examples.

Commands that target a member accept either an `@username` argument or a reply to that member's message. Group moderation commands require group-admin rights. Sudo management and global statistics are owner-only.
## Central activity log group

Set `LOG_CHAT_ID` in `.env` to the numeric ID of a private Telegram log group (for example, `-1001234567890`). Add EDITBOT to that log group so it can post messages. The log reports bot startup, users who press `/start` in private chat, and when EDITBOT itself is added to or removed from a group. It includes the group title, numeric ID, public link when available, and the actor's name/ID. For private groups, Telegram may not expose an invite link, so the log will say it is unavailable. Keep the log group restricted to trusted admins because it may contain private group names and activity.

See .env.example. Keep `.env` private and never commit bot tokens, API credentials, or database credentials.

## Safe defaults

- Anti-promo is OFF until an admin enables it.
- Anti-flood is OFF until an admin enables it.
- Edited-message deletion is OFF; edit history is still recorded.
- Only configured owners can add or remove Sudo users.
- Sudo users and group admins are exempt from edit deletion.
- Bio/channel scanning respects Telegram's access controls.
