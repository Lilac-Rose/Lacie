"""
constants.py — Centralised Discord IDs and threshold values for the bot.

All hardcoded IDs (users, guild, channels, roles, emojis) live here so they
can be updated in one place without hunting through individual cog files.
"""

# --- Owner / Admin ---
LILAC_ID = 252130669919076352         # Bot owner; bypasses all permission checks

# --- Guild ---
GUILD_ID = 876772600704020530         # Primary server the bot operates in

# --- Channels ---
WELCOME_CHANNEL_ID = 876772600704020533    # Where welcome messages are posted
FALLBACK_CHANNEL_ID = 876772600704020533   # Fallback channel when a specific channel is unavailable
LOG_CHANNEL_ID = 1440055015711703242       # Default channel for mod/system log messages
ADMIN_CHANNEL_ID = 1470441786810826884     # Staff-only admin channel
APPROVAL_CHANNEL_ID = 1424145004976275617  # Where pending approval embeds (infractions, credits) are sent
BACKUP_CHANNEL_ID = 946421558778417172     # Backup/archive channel
NOTIFICATION_CHANNEL_ID = 1424145004976275617  # General notification channel (same as approval)
COMMIT_CHANNEL_IDS = [876777562599194644, 1437941632849940563, 1470441786810826884]  # Git webhook targets

# --- Roles ---
BIRTHDAY_ROLE_ID = 1113751318918602762     # Temporary role assigned on a member's birthday
BOT_TRAP_ROLE_ID = 1439354601672282335     # Role given to suspected bots; blocks welcome message
SERVER_ADMIN_ROLE_ID = 952560403970416722  # General staff/admin role
BOT_DEV_ROLE_ID = 1470439484549234866      # Bot developer role with elevated permissions

# --- Emojis ---
SALT_EMOJI_ID = 1074583707459010560        # Custom :salt: emoji used in reactions

# --- Thresholds ---
NEW_MEMBER_THRESHOLD_DAYS = 7  # Members newer than this many days are considered "new"
