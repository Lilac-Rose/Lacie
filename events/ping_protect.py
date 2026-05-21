import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path
import aiosqlite

NO_PINGS_ROLE_ID = 1439583411517001819
PINGS_OK_ROLE_ID = 1439583327844827227

PROTECTED_USER_ID = 252130669919076352  # only lilac gets ping tracking

DB_PATH = Path(__file__).parent.parent / "data" / "ping_protect.db"


class PingProtect(commands.GroupCog, name="noping"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ping_counts (
                    user_id INTEGER PRIMARY KEY,
                    count INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS allowlists (
                    protected_user_id INTEGER,
                    allowed_user_id INTEGER,
                    PRIMARY KEY (protected_user_id, allowed_user_id)
                )
            """)
            await db.commit()

    def _has_permission(self, member: discord.Member) -> bool:
        return (
            member.id == PROTECTED_USER_ID or
            any(r.id == NO_PINGS_ROLE_ID for r in member.roles)
        )

    async def _is_allowed(self, protected_user_id: int, pinger_id: int) -> bool:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT 1 FROM allowlists WHERE protected_user_id = ? AND allowed_user_id = ?",
                (protected_user_id, pinger_id)
            )
            return await cursor.fetchone() is not None

    def _get_subject_pronoun(self, member: discord.Member | None) -> str:
        if not member:
            return "They"
        role_names = {r.name.lower() for r in member.roles}
        if "he/him" in role_names:
            return "He"
        if "she/her" in role_names:
            return "She"
        if "it/its" in role_names:
            return "It"
        return "They"

    def _get_verb(self, pronoun: str) -> str:
        return "have" if pronoun == "They" else "has"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        for user in message.mentions:
            member = message.guild.get_member(user.id)

            if member and any(r.id == PINGS_OK_ROLE_ID for r in member.roles):
                continue

            is_protected = (
                user.id == PROTECTED_USER_ID or
                (member and any(r.id == NO_PINGS_ROLE_ID for r in member.roles))
            )
            if not is_protected:
                continue

            if await self._is_allowed(user.id, message.author.id):
                continue

            if user.id == PROTECTED_USER_ID:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("""
                        INSERT INTO ping_counts (user_id, count) VALUES (?, 1)
                        ON CONFLICT(user_id) DO UPDATE SET count = count + 1
                    """, (message.author.id,))
                    await db.commit()
                await message.reply("Please don't ping faer", mention_author=False)
            else:
                pronoun = self._get_subject_pronoun(member)
                verb = self._get_verb(pronoun)
                await message.reply(
                    f"Please don't ping {user.name}. {pronoun} {verb} pings disabled.",
                    mention_author=False
                )

    @app_commands.command(name="allow", description="Allow someone to ping you")
    @app_commands.describe(user="The user to allow")
    async def allow(self, interaction: discord.Interaction, user: discord.Member):
        if not isinstance(interaction.user, discord.Member) or not self._has_permission(interaction.user):
            await interaction.response.send_message("You need the no-pings role to use this.", ephemeral=True)
            return

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT OR IGNORE INTO allowlists (protected_user_id, allowed_user_id)
                VALUES (?, ?)
            """, (interaction.user.id, user.id))
            await db.commit()You need the no-pings role to use this.", ephemeral=True)
            return

        async with aiosqlite.connect(DB_PATH) as db:

        await interaction.response.send_message(f"✅ {user.display_name} can now ping you.", ephemeral=True)

    @app_commands.command(name="remove", description="Remove someone from your ping allowlist")
    @app_commands.describe(user="The user to remove")
    async def remove(self, interaction: discord.Interaction, user: discord.Member):
        if not isinstance(interaction.user, discord.Member) or not self._has_permission(interaction.user):
            await interaction.response.send_message("You need the no-pings role to use this.", ephemeral=True)
            return

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM allowlists WHERE protected_user_id = ? AND allowed_user_id = ?",
                (interaction.user.id, user.id)
            )
            await db.commit()

        await interaction.response.send_message(f"✅ {user.display_name} can no longer ping you.", ephemeral=True)

    @app_commands.command(name="list", description="View your ping allowlist")
    async def list_allowed(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not self._has_permission(interaction.user):
            await interaction.response.send_message("You need the no-pings role to use this.", ephemeral=True)
            return

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT allowed_user_id FROM allowlists WHERE protected_user_id = ?",
                (interaction.user.id,)
            )
            rows = await cursor.fetchall()

        if not rows:
            await interaction.response.send_message("Your allowlist is empty.", ephemeral=True)
            return

        mentions = "\n".join(f"<@{row[0]}>" for row in rows)
        await interaction.response.send_message(f"**Your ping allowlist:**\n{mentions}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PingProtect(bot))
