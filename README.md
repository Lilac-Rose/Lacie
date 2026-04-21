# Lacie Bot

Lacie is a custom Discord bot built for a private server. It handles moderation, user engagement, server utilities, and a handful of fun or creative features. Everything here is tailored to one specific community.

## What it does

**Moderation and admin tools**
Staff can warn, track, and manage members. The bot records infractions in a database and lets users check their own history privately via `/infractions`. Admins also have access to tools like `!salt` (react to a user's next message with a salt emoji) and `!sendmessage` / `!schedulemessage` for sending or scheduling messages to channels.

**Role management**
Members can self-assign color roles from a preset list using `/color set`, remove them with `/color remove`, and browse what's available with `/color list`. Prestige members (those with high-tier server roles) can additionally use `/prestige color` to display the color of a lower prestige role without losing their position in the hierarchy. The bot handles all the role swapping automatically.

Role tracking runs in the background: whenever a member's roles change, they're saved to a database. If someone leaves and rejoins, their roles are restored automatically. Members can manually trigger a sync with `/syncroles` or verify what's saved with `/checkroles`.

**XP and leveling**
Activity is tracked through an XP system. `/xp rank` shows a user's rank, and `/xp top` shows the server leaderboard, filterable by lifetime, annual, monthly, weekly, or daily XP.

**Sparkles**
A secondary currency or engagement metric. `/sparkle check`, `/sparkle leaderboard`, `/sparkle info`, and `/sparkle stats` give members and admins visibility into the system.

**Profile cards**
Members can set and display a personal profile with `/profile set` and `/profile view`. Font choices are available and can be previewed with `/profile fonts`.

**Avatar effects**
`/avatar` supports a range of image effects: grayscale, inverse, bitcrush, Canny edge detection, Kuwahara filter, explode, an Obama-style mosaic, and a Bad Apple animation that tiles avatar images as the fill.

**Giveaways**
Admins can start a giveaway with `/giveaway start`, specifying a prize and a deadline (either a duration like `2h` or a date/time string). The bot posts an embed, collects reactions, and announces a winner automatically when the deadline passes. Admins can re-roll from the result embed.

**Emote credits**
The server tracks who made each custom emoji and sticker. Any member can look up a credit with `/emote_credit`, submit a new one with `/emote_credits_add`, or propose a correction with `/emote_credits_update`. Submissions go through an admin approval flow before being added. `/emote_artists` lists all credited artists, and `/emote_by_artist` shows everything credited to a specific person.

**Quote images**
`/quote` takes a message ID and renders it as a stylized image: the author's avatar on the left with an angled gradient fade, the message text on the right, and an attribution line below. Supports grayscale mode and works in threads.

**Games**
Connect Four, Tic-Tac-Toe, and Minesweeper (with Easy, Medium, and Hard difficulty). Minesweeper tracks per-user stats via `/minesweeper_stats`.

**Wordle**
A daily Wordle game running on the server. Members start with `/wordle`, submit guesses with `/wordle_guess`, and can check their stats or the server-wide stats with `/wordle_stats` and `/wordle_serverstats`.

**Reminders**
Members can set personal reminders by duration (`/reminder set 10m check the oven`) or by specific date and time (`/reminder at "April 5 3pm" meeting`). They can list, remove, or clear their active reminders.

**Birthdays**
Members can save their birthday with `/birthday set` and a timezone. `/birthday list` shows birthdays for a given month.

**Suggestions**
`/suggest submit` lets members send a suggestion for the server or bot. Suggestions can be viewed individually, listed with status filters, and stats can be checked per user.

**Server and bot info**
`/stats server` shows general server and bot statistics. `/stats messages` and `/stats words` show message and word frequency data. `/ping` reports WebSocket latency, API latency, and database latency.

**Utility**
`/faq` shows a server-specific FAQ. `/help` opens a categorized, interactive command reference.

**Fun**
`/bonk` sends a bonk image at another user. `/coinflip` and `/diceroll` do what they say. `/meow` outputs a random cat noise.

## Notes

Contributions are not accepted. This bot is built for one server and is not intended for general use.

This project is private. Do not redistribute without permission.
