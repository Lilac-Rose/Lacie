import discord
from discord import app_commands
from discord.ext import commands
import json
from pathlib import Path
from moderation.loader import ModerationBase
from utils.logger import get_logger

logger = get_logger(__name__)

# Maps display name -> original role ID for every role that gets a color copy.
# The actual color copy role IDs are stored in prestige_color_roles.json after setup,
# since we don't know them until the bot creates them.
PRESTIGE_ROLES: dict[str, int] = {
    "Acclaimed Ritualist": 1230018526786617364,
    "The Ritualist": 1296056657784340480,
    "Legendary Ritualist": 1296056209543008287,
    "Elite Ritualist": 1296055376009101384,
    "Honorable Ritualist": 1213171315259736155,
    "Content Creator": 1038402681376612413,
}

# Color copies get placed just above this role in the hierarchy
ACCLAIMED_ROLE_ID = 1230018526786617364

# Persists the original_id -> copy_id mapping across restarts
DATA_PATH = Path(__file__).parent.parent / "data" / "prestige_color_roles.json"


def load_color_role_ids() -> dict[str, int]:
    """Returns {str(original_role_id): color_copy_role_id}"""
    if DATA_PATH.exists():
        with open(DATA_PATH) as f:
            return json.load(f)
    return {}


def save_color_role_ids(data: dict[str, int]):
    """Persist the original_id -> color_copy_id mapping to DATA_PATH as JSON."""
    DATA_PATH.parent.mkdir(exist_ok=True)
    with open(DATA_PATH, "w") as f:
        json.dump(data, f, indent=2)


class PrestigeColor(commands.Cog):
    """Cog providing the /prestige slash command group.

    Manages color-copy roles for prestige (high-ranked) members. Each prestige
    role gets a duplicate "color copy" role placed just above Acclaimed Ritualist
    in the hierarchy so its color overrides the prestige role below it.

    Subcommands:
    - ``/prestige setup``       — (admin) Create color copy roles for each prestige role.
    - ``/prestige color``       — Switch your active prestige color.
    - ``/prestige removecolor`` — Remove your prestige color.
    """

    def __init__(self, bot):
        self.bot = bot

    prestige_group = app_commands.Group(name="prestige", description="Prestige color commands")

    @prestige_group.command(
        name="setup",
        description="[ADMIN] Create prestige color copy roles above Acclaimed Ritualist."
    )
    @ModerationBase.is_admin()
    async def setup(self, interaction: discord.Interaction):
        """Create or recreate color copy roles for every prestige role (admin only).

        Skips roles whose copies already exist in the server. Positions each new
        copy just above ACCLAIMED_ROLE_ID so it wins the color resolution order.
        The resulting original_id -> copy_id mapping is saved to DATA_PATH.
        """
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Server only.", ephemeral=True)
            return

        acclaimed = guild.get_role(ACCLAIMED_ROLE_ID)
        if not acclaimed:
            await interaction.followup.send("Could not find the Acclaimed Ritualist role.", ephemeral=True)
            return

        existing = load_color_role_ids()
        created = []
        skipped = []

        for name, original_id in PRESTIGE_ROLES.items():
            # Skip if already set up and the copy role still exists in the server
            if str(original_id) in existing:
                existing_copy = guild.get_role(existing[str(original_id)])
                if existing_copy:
                    skipped.append(name)
                    continue
            # If we get here, either this role was never set up or the copy got deleted — (re)create it

            original_role = guild.get_role(original_id)
            if not original_role:
                await interaction.followup.send(
                    f"Could not find original role for **{name}** (ID {original_id}).", ephemeral=True
                )
                return

            # Create a color-only copy — same name, same color, zero permissions
            new_role = await guild.create_role(
                name=name,
                color=original_role.color,
                reason="Prestige color copy role — color only, no permissions"
            )

            # Place it just above Acclaimed Ritualist so it overrides the original's color
            try:
                await new_role.edit(position=acclaimed.position + 1)
            except discord.HTTPException as e:
                logger.warning(f"Could not set position for prestige color copy '{name}': {e}")

            existing[str(original_id)] = new_role.id
            created.append(name)

        save_color_role_ids(existing)

        lines = []
        if created:
            lines.append(f"Created: {', '.join(created)}")
        if skipped:
            lines.append(f"Already existed: {', '.join(skipped)}")
        await interaction.followup.send("\n".join(lines) or "Nothing to do.", ephemeral=True)

    async def prestige_autocomplete(self, interaction: discord.Interaction, current: str):
        """Autocomplete callback for the ``prestige`` parameter of /prestige color.

        Filters the autocomplete list to only the prestige roles the invoking
        member actually holds (no point offering roles they can't pick). Color
        copy IDs that haven't been set up yet are also excluded.
        """
        # Only show roles the user actually has — no point listing ones they can't pick
        color_ids = load_color_role_ids()
        member = interaction.user
        if not isinstance(member, discord.Member) or not interaction.guild:
            return []

        choices = []
        for name, original_id in PRESTIGE_ROLES.items():
            if str(original_id) not in color_ids:
                continue
            original_role = interaction.guild.get_role(original_id)
            if original_role and original_role in member.roles:
                if current.lower() in name.lower():
                    choices.append(app_commands.Choice(name=name, value=name))

        return choices

    @prestige_group.command(name="color", description="Choose which prestige color to display.")
    @app_commands.describe(prestige="The prestige role whose color you want to display.")
    @app_commands.autocomplete(prestige=prestige_autocomplete)
    async def color(self, interaction: discord.Interaction, prestige: str):
        """Equip a prestige color role copy, swapping out any previously active copy.

        Prevents a user from equipping the color copy of their highest prestige role
        since the original already controls the display color at that rank. When
        switching colors, the old copy is removed and the original role is restored
        before the new copy is added, so the user never loses a prestige title.

        Parameters
        ----------
        prestige:
            The display name of the prestige role (from autocomplete).
        """
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Server only.", ephemeral=True)
            return

        color_ids = load_color_role_ids()
        original_id = PRESTIGE_ROLES.get(prestige)

        if not original_id:
            await interaction.followup.send("Invalid choice. Use the autocomplete options.", ephemeral=True)
            return

        if str(original_id) not in color_ids:
            await interaction.followup.send(
                "Prestige colors haven't been set up yet. An admin needs to run `/prestige setup`.",
                ephemeral=True
            )
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            # can come back as a plain User in some edge cases
            member = await guild.fetch_member(interaction.user.id)

        original_role = guild.get_role(original_id)
        if not original_role or original_role not in member.roles:
            await interaction.followup.send(
                f"You don't have the **{prestige}** role.", ephemeral=True
            )
            return

        color_role = guild.get_role(color_ids[str(original_id)])
        if not color_role:
            await interaction.followup.send(
                "Color copy role not found. An admin needs to run `/prestige setup` again.",
                ephemeral=True
            )
            return

        # Block equipping the color copy of the user's highest prestige role.
        # The copy sits lower in the hierarchy than the original, so swapping it out
        # would actually demote the user's display position in the member list.
        member_prestige_roles = [
            guild.get_role(pid)
            for pid in PRESTIGE_ROLES.values()
            if guild.get_role(pid) and guild.get_role(pid) in member.roles
        ]
        if member_prestige_roles:
            highest_prestige = max(member_prestige_roles, key=lambda r: r.position)
            if highest_prestige.id == original_id:
                await interaction.followup.send(
                    f"**{prestige}** is already your highest role — its color is already showing correctly. "
                    f"You can only equip a color for a role that isn't your highest.",
                    ephemeral=True
                )
                return

        all_copy_ids = set(color_ids.values())

        # If they had a different color active, swap it out and give back the original.
        # e.g. switching from Elite copy -> Honorable copy restores the Elite original.
        copy_to_original = {v: guild.get_role(int(k)) for k, v in color_ids.items()}
        old_copies = [r for r in member.roles if r.id in all_copy_ids and r.id != color_role.id]
        if old_copies:
            await member.remove_roles(*old_copies, reason="Switching prestige color")
            to_restore = [
                copy_to_original[r.id] for r in old_copies
                if copy_to_original.get(r.id)
            ]
            if to_restore:
                await member.add_roles(*to_restore, reason="Restoring prestige role after color switch")

        # Give the chosen color copy, pull the original so there's no duplicate name floating around
        roles_to_add = [] if color_role in member.roles else [color_role]
        roles_to_remove = [original_role] if original_role in member.roles else []
        if roles_to_add:
            await member.add_roles(*roles_to_add, reason="User selected prestige color")
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Replaced by prestige color copy")

        await interaction.followup.send(f"Your prestige color is now **{prestige}**!", ephemeral=True)

    @prestige_group.command(name="removecolor", description="Remove your prestige color.")
    async def removecolor(self, interaction: discord.Interaction):
        """Remove all prestige color copy roles and restore the original prestige roles."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Server only.", ephemeral=True)
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            member = await guild.fetch_member(interaction.user.id)

        color_ids = load_color_role_ids()
        all_copy_ids = set(color_ids.values())
        to_remove = [r for r in member.roles if r.id in all_copy_ids]

        if not to_remove:
            await interaction.followup.send("You don't have a prestige color set.", ephemeral=True)
            return

        await member.remove_roles(*to_remove, reason="User removed prestige color")

        # Give back the originals they had copied — they should never lose their prestige roles
        copy_to_original = {v: guild.get_role(int(k)) for k, v in color_ids.items()}
        to_restore = [
            copy_to_original[r.id] for r in to_remove
            if copy_to_original.get(r.id)
        ]
        if to_restore:
            await member.add_roles(*to_restore, reason="Restoring prestige role after color removal")

        await interaction.followup.send("Your prestige color has been removed.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(PrestigeColor(bot))
