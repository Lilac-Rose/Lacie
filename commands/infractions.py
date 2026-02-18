"""Command for users to view their own moderation infractions via DM."""
import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
from pathlib import Path


class InfractionsCommand(commands.Cog):
    """Command for users to view their own infractions"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Path to moderation database (go up to project root, then into moderation/)
        self.db_path = Path(__file__).parent.parent / "data" / "moderation.db"

    @app_commands.command(name="infractions", description="View your infractions in this server")
    async def infractions(self, interaction: discord.Interaction):
        """DM the user their active infractions without showing moderator names."""
        await interaction.response.defer(ephemeral=True)

        try:
            # Connect to the moderation database
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # Fetch active infractions for this user in this guild
            c.execute("""
                SELECT id, type, reason, timestamp
                FROM infractions
                WHERE user_id=? AND guild_id=? AND removed=0
                ORDER BY timestamp DESC
            """, (interaction.user.id, interaction.guild.id))
            
            results = c.fetchall()
            conn.close()

            if not results:
                await interaction.followup.send("You have no active infractions in this server.", ephemeral=True)
                return

            # Build rows for the table
            rows = []
            for row in results:
                inf_id, inf_type, reason, timestamp = row
                timestamp_formatted = timestamp.replace("T", " ")[:19]
                reason_text = reason or "None"

                rows.append({
                    "id": str(inf_id),
                    "type": inf_type,
                    "timestamp": timestamp_formatted,
                    "reason": reason_text
                })

            # Prepare table formatting
            widths = {key: max(len(key), *(len(r[key]) for r in rows)) for key in rows[0].keys()}
            header = " | ".join(f"{key.capitalize():{widths[key]}}" for key in rows[0].keys())
            separator = "-" * len(header)

            # Build pages (in case there are many infractions)
            chunk_size = 1800
            pages = []
            current_chunk = [header, separator]
            char_count = len("```md\n") + len(header) + len(separator) + 2

            for r in rows:
                line = " | ".join(f"{r[key]:{widths[key]}}" for key in r.keys())
                line_len = len(line) + 1
                if char_count + line_len > chunk_size:
                    pages.append("```md\n" + "\n".join(current_chunk) + "\n```")
                    current_chunk = [header, separator]
                    char_count = len("```md\n") + len(header) + len(separator) + 2
                current_chunk.append(line)
                char_count += line_len

            if current_chunk:
                pages.append("```md\n" + "\n".join(current_chunk) + "\n```")

            # Try to DM the user
            try:
                dm_header = f"**Your Active Infractions in {interaction.guild.name}**\n\n"
                
                # Send all pages to DM
                for page in pages:
                    await interaction.user.send(dm_header + page)
                    dm_header = ""  # Only show header on first message

                await interaction.followup.send("Your infractions have been sent to your DMs!", ephemeral=True)

            except discord.Forbidden:
                await interaction.followup.send(
                    "I couldn't DM you. Please enable DMs from server members and try again.",
                    ephemeral=True
                )
            except Exception as e:
                await interaction.followup.send(f"Error sending DM: {e}", ephemeral=True)

        except sqlite3.Error as e:
            await interaction.followup.send(f"Database error: {e}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(InfractionsCommand(bot))