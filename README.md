# EDITBOT — Advanced Telegram Anti-Promotion Bot

EDITBOT helps group admins moderate unsolicited Telegram group promotion.

## Features

- Detect Telegram invite links in group messages.
- Check a member's bio only when Telegram makes that profile data accessible to the bot.
- If a public channel handle is visible in accessible profile text, inspect a bounded number of recent public posts for group invite links.
- Run checks on ordinary messages too, including short greetings such as Hi or Hello.
- Per-group anti-promo enable and disable.
- Admin-only approve, unapprove, scan, unmute, and moderation-log commands.
- MongoDB storage and short-lived profile-result caching.

## Important Telegram limitation

A Telegram bot cannot forcibly open every member's private profile data or enumerate every channel linked to arbitrary users. Telegram may not expose a member's bio or linked personal channel to the bot. EDITBOT treats inaccessible data as unavailable, not as proof of wrongdoing. It scans public channel posts only when a public channel handle is actually available to the bot. No private-channel or privacy bypass is implemented.

## Setup

1. Create a bot with BotFather and obtain its token.
2. Obtain API_ID and API_HASH from my.telegram.org.
3. Create a MongoDB database and connection URI.
4. Copy .env.example to .env and fill in the values.
5. Install dependencies with: pip install -r requirements.txt
6. Run: python main.py
7. Add the bot to your group as an administrator and grant permission to restrict members.
8. Enable it in each group with /antipromo on.

## Commands

- /antipromo on — enable anti-promo checks in this group.
- /antipromo off — disable anti-promo checks.
- /antipromo status — show current status.
- /approve @username — exempt a member in this group (or reply to them).
- /unapprove @username — remove the exemption.
- /approvedusers — list approved members.
- /approve_link https://t.me/+invite — allow a specific invite link in this group.
- /unapprove_link https://t.me/+invite — remove an approved invite link.
- /approved_links — list approved invite links.
- /scan @username — inspect accessible profile/channel information (or reply to a member).
- /unmute @username — unmute a member (or reply to them).
- /promologs — show recent moderation actions.

All moderation commands are restricted to group admins. Owner IDs in OWNER_IDS are also recognized.

## Environment variables

See .env.example. Keep .env private and never commit bot tokens or database credentials.

## Current scope

This first implementation focuses on anti-promotion moderation. It does not claim 100% profile/channel visibility because Telegram API permissions do not allow that. Test in a private test group before enabling it in a live community.
