import os
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite

OWNER_ID = 252130669919076352

RCON_HOST = os.getenv("RCON_HOST")
RCON_PORT = int(os.getenv("RCON_PORT", "25575"))
RCON_PASSWORD = os.getenv("RCON_PASSWORD")
SERVER_IP = os.getenv("MC_SERVER_IP", "vanilla.lilacrose.dev")

DB_PATH = Path(__file__).parent.parent / "data" / "whitelist.db"


async def init_db():
    """Create the whitelist table if it doesn't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS whitelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                minecraft_username TEXT NOT NULL UNIQUE,
                discord_user_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_at TEXT NOT NULL
            )
        """)
        await db.commit()


async def rcon_command(cmd: str) -> str:
    """Minimal async RCON client — avoids mcrcon's signal.signal() thread issue.

    Implements the Source RCON protocol:
    1. Open TCP connection.
    2. Send a SERVERDATA_AUTH (type 3) packet with the password.
    3. Send a SERVERDATA_EXECCOMMAND (type 2) packet with the command.
    4. Return the server's response body string.

    Parameters
    ----------
    cmd:
        The Minecraft server command to execute (without leading slash).

    Returns
    -------
    str
        The raw response text from the server.

    Raises
    ------
    ValueError
        If RCON authentication fails (wrong password).
    """
    import struct

    RCON_LOGIN = 3
    RCON_COMMAND = 2
    REQ_ID = 1

    def _pack(req_id: int, ptype: int, body: str) -> bytes:
        payload = body.encode("utf-8") + b"\x00\x00"
        length = 4 + 4 + len(payload)
        return struct.pack("<iii", length, req_id, ptype) + payload

    def _unpack(data: bytes):
        length, req_id, ptype = struct.unpack_from("<iii", data, 0)
        body = data[12 : 8 + length - 2].decode("utf-8", errors="replace")
        return req_id, ptype, body

    reader, writer = await asyncio.open_connection(RCON_HOST, RCON_PORT)
    try:
        # Authenticate
        writer.write(_pack(REQ_ID, RCON_LOGIN, RCON_PASSWORD))
        await writer.drain()
        raw = await reader.read(4096)
        auth_id, _, _ = _unpack(raw)
        if auth_id == -1:
            raise ValueError("RCON authentication failed — wrong password?")

        # Send command
        writer.write(_pack(REQ_ID, RCON_COMMAND, cmd))
        await writer.drain()
        raw = await reader.read(4096)
        _, _, response = _unpack(raw)
        return response
    finally:
        writer.close()
        await writer.wait_closed()


PAGE_SIZE = 10


class WhitelistListView(discord.ui.View):
    def __init__(self, rows: list, *, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.rows = rows
        self.page = 0
        self.total_pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title="Minecraft Whitelist", color=0x57F287)
        page_rows = self.rows[self.page * PAGE_SIZE : (self.page + 1) * PAGE_SIZE]

        pending = [r for r in page_rows if r[2] == "pending"]
        approved = [r for r in page_rows if r[2] == "approved"]

        if pending:
            lines = []
            for mc_name, discord_id, _, requested_at in pending:
                user_ref = f"<@{discord_id}>" if discord_id else "No Discord linked"
                lines.append(f"• `{mc_name}` — {user_ref} *(requested {requested_at[:10]})*")
            embed.add_field(name=f"⏳ Pending", value="\n".join(lines), inline=False)

        if approved:
            lines = []
            for mc_name, discord_id, _, _ in approved:
                user_ref = f"<@{discord_id}>" if discord_id else "No Discord linked"
                lines.append(f"• `{mc_name}` — {user_ref}")
            embed.add_field(name=f"✅ Approved", value="\n".join(lines), inline=False)

        total_pending = sum(1 for r in self.rows if r[2] == "pending")
        total_approved = sum(1 for r in self.rows if r[2] == "approved")
        embed.set_footer(text=f"Page {self.page + 1}/{self.total_pages} • {total_pending} pending, {total_approved} approved")
        return embed

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class Whitelist(commands.GroupCog, name="whitelist"):
    """Minecraft whitelist request and management commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """Initialise the DB table on cog load."""
        await init_db()

    # ── /whitelist request ─────────────────────────────────────────────────────

    @app_commands.command(name="request", description="Request to be added to the Minecraft server whitelist")
    @app_commands.describe(minecraft_username="Your Minecraft username")
    async def whitelist_request(self, interaction: discord.Interaction, minecraft_username: str):
        """Submit a whitelist request for a Minecraft username.

        Rejects duplicate requests for the same username. On acceptance, stores
        a pending record so the owner can approve via /whitelist add.
        """
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT status FROM whitelist WHERE minecraft_username = ? COLLATE NOCASE",
                (minecraft_username,)
            ) as cur:
                row = await cur.fetchone()

            if row:
                if row[0] == "approved":
                    await interaction.followup.send(
                        f"`{minecraft_username}` is already on the whitelist!", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"There's already a pending request for `{minecraft_username}`.", ephemeral=True
                    )
                return

            await db.execute(
                "INSERT INTO whitelist (minecraft_username, discord_user_id, status, requested_at) VALUES (?, ?, 'pending', ?)",
                (minecraft_username, interaction.user.id, datetime.now(timezone.utc).isoformat())
            )
            await db.commit()

        await interaction.followup.send(
            f"Your whitelist request for `{minecraft_username}` has been submitted! "
            f"You'll receive a DM when it's approved.",
            ephemeral=True
        )

    # ── /whitelist list ────────────────────────────────────────────────────────

    @app_commands.command(name="list", description="View whitelist requests and approved players")
    async def whitelist_list(self, interaction: discord.Interaction):
        """List all pending and approved whitelist entries (owner only)."""
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT minecraft_username, discord_user_id, status, requested_at FROM whitelist ORDER BY status DESC, requested_at ASC"
                ) as cur:
                    rows = await cur.fetchall()

            if not rows:
                await interaction.followup.send("No whitelist entries found.", ephemeral=True)
                return

            view = WhitelistListView(rows)
            await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)
            raise

    # ── /whitelist add ─────────────────────────────────────────────────────────

    @app_commands.command(name="add", description="Add a player to the Minecraft whitelist via RCON")
    @app_commands.describe(minecraft_username="The Minecraft username to whitelist")
    async def whitelist_add(self, interaction: discord.Interaction, minecraft_username: str):
        """Approve a whitelist request via RCON and DM the requester (owner only).

        If a pending request exists for the username, marks it as approved and
        notifies the linked Discord user. If no request exists, inserts an
        approved record directly.
        """
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            result = await rcon_command(f"whitelist add {minecraft_username}")
        except Exception as e:
            await interaction.followup.send(f"RCON error: `{e}`", ephemeral=True)
            return

        discord_user_id = None
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT discord_user_id FROM whitelist WHERE minecraft_username = ? COLLATE NOCASE",
                (minecraft_username,)
            ) as cur:
                row = await cur.fetchone()

            if row:
                discord_user_id = row[0]
                await db.execute(
                    "UPDATE whitelist SET status = 'approved' WHERE minecraft_username = ? COLLATE NOCASE",
                    (minecraft_username,)
                )
            else:
                # No prior request — insert a new approved record
                await db.execute(
                    "INSERT INTO whitelist (minecraft_username, discord_user_id, status, requested_at) VALUES (?, NULL, 'approved', ?)",
                    (minecraft_username, datetime.now(timezone.utc).isoformat())
                )
            await db.commit()

        dm_note = ""
        if discord_user_id:
            try:
                user = await self.bot.fetch_user(discord_user_id)
                await user.send(
                    f"Hey! Your whitelist request for **{minecraft_username}** has been approved! 🎉\n"
                    f"You can now join the Minecraft server at `{SERVER_IP}`."
                )
                dm_note = f"\nDM sent to <@{discord_user_id}>."
            except discord.Forbidden:
                dm_note = f"\n⚠️ Couldn't DM <@{discord_user_id}> (DMs disabled)."
            except Exception as e:
                dm_note = f"\n⚠️ DM to <@{discord_user_id}> failed: {e}"

        await interaction.followup.send(
            f"✅ Added `{minecraft_username}` to the whitelist.\nServer: `{result}`{dm_note}",
            ephemeral=True
        )

    # ── /whitelist remove ──────────────────────────────────────────────────────

    @app_commands.command(name="remove", description="Remove a player from the Minecraft whitelist via RCON")
    @app_commands.describe(minecraft_username="The Minecraft username to remove")
    async def whitelist_remove(self, interaction: discord.Interaction, minecraft_username: str):
        """Remove a player from the Minecraft whitelist via RCON and the DB (owner only)."""
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            result = await rcon_command(f"whitelist remove {minecraft_username}")
        except Exception as e:
            await interaction.followup.send(f"RCON error: `{e}`", ephemeral=True)
            return

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM whitelist WHERE minecraft_username = ? COLLATE NOCASE",
                (minecraft_username,)
            )
            await db.commit()

        await interaction.followup.send(
            f"🗑️ Removed `{minecraft_username}` from the whitelist.\nServer: `{result}`",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Whitelist(bot))
