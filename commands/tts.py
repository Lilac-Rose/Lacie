import asyncio
import os
import re
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from utils.logger import get_logger

logger = get_logger(__name__)

MAX_MESSAGE_LENGTH = 150
RATE_LIMIT_SECONDS = 3.0
IDLE_TIMEOUT_SECONDS = 300
TTS_VOICE = "en-US-AriaNeural"

URL_PATTERN = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)
CUSTOM_EMOJI_PATTERN = re.compile(r'<a?:(\w+):\d+>')

DB_PATH = Path(__file__).parent.parent / "data" / "tts.db"


class TTS(commands.GroupCog, name="tts"):
    """GroupCog providing voice-channel TTS for muted members.

    When active in a guild, messages sent to the active voice channel's text
    chat by muted members are synthesised with edge-tts (falling back to gTTS)
    and played through the bot's voice connection.

    Features:
    - Per-guild asyncio queue so messages play sequentially without overlap.
    - Rate limit of one TTS per user per RATE_LIMIT_SECONDS.
    - Automatic disconnect after IDLE_TIMEOUT_SECONDS of queue inactivity.
    - Automatic disconnect if all human members leave the voice channel.
    - Optional TTS nickname stored in tts.db to override the Discord username.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> voice_channel_id currently being listened to
        self.active_channels: dict[int, int] = {}
        # guild_id -> asyncio.Queue of (tts_name, text) tuples
        self.queues: dict[int, asyncio.Queue] = {}
        # guild_id -> queue processor Task
        self.queue_tasks: dict[int, asyncio.Task] = {}
        # (guild_id, user_id) -> last tts timestamp (monotonic)
        self.rate_limits: dict[tuple[int, int], float] = defaultdict(float)

    async def cog_load(self):
        """Create the tts_nicks table if it doesn't exist."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tts_nicks (
                    user_id INTEGER PRIMARY KEY,
                    nickname TEXT NOT NULL
                )
            """)
            await db.commit()

    async def _get_tts_name(self, user_id: int, fallback: str) -> str:
        """Return the user's saved TTS nickname, or their Discord username as fallback."""
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT nickname FROM tts_nicks WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
        return row[0] if row else fallback

    async def _generate_tts(self, text: str, filepath: str) -> bool:
        """Generate TTS audio to filepath. Tries edge-tts first, falls back to gTTS.

        Parameters
        ----------
        text:
            The text to synthesise.
        filepath:
            Path to write the resulting MP3 file to.

        Returns
        -------
        bool
            True if audio was generated successfully, False otherwise.
        """
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, TTS_VOICE)
            await communicate.save(filepath)
            return True
        except Exception:
            pass
        try:
            from gtts import gTTS
            loop = asyncio.get_event_loop()
            tts = gTTS(text=text, lang='en')
            await loop.run_in_executor(None, tts.save, filepath)
            return True
        except Exception as e:
            logger.error(f"TTS generation failed: {e}")
            return False

    async def _process_queue(self, guild_id: int):
        """Sequentially process TTS entries for a guild.

        Waits up to IDLE_TIMEOUT_SECONDS for the next queue item. If the timeout
        fires, disconnects the bot and cleans up state. Exits if the voice
        connection is lost between items.
        """
        while True:
            queue = self.queues.get(guild_id)
            if not queue:
                return

            try:
                item = await asyncio.wait_for(queue.get(), timeout=IDLE_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                guild = self.bot.get_guild(guild_id)
                channel_id = self.active_channels.get(guild_id)
                self._cleanup(guild_id)
                if guild:
                    vc = guild.voice_client
                    if isinstance(vc, discord.VoiceClient):
                        await vc.disconnect()
                    if channel_id:
                        channel = guild.get_channel(channel_id)
                        if isinstance(channel, discord.VoiceChannel):
                            try:
                                await channel.send("No messages for a while, so I left. TTS stopped!")
                            except Exception:
                                pass
                return
            except asyncio.CancelledError:
                return

            name, text = item
            guild = self.bot.get_guild(guild_id)
            if not guild:
                self._cleanup(guild_id)
                return

            vc = guild.voice_client
            if not isinstance(vc, discord.VoiceClient) or not vc.is_connected():
                self._cleanup(guild_id)
                return

            tmpfile = None
            try:
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                    tmpfile = f.name

                success = await self._generate_tts(f"{name} said: {text}", tmpfile)

                if success and vc.is_connected():
                    # Wait for any currently playing audio to finish before queuing the next
                    while vc.is_playing():
                        await asyncio.sleep(0.1)

                    done_event = asyncio.Event()

                    def after_play(error):
                        if error:
                            logger.error(f"TTS playback error: {error}")
                        done_event.set()

                    vc.play(discord.FFmpegPCMAudio(tmpfile), after=after_play)
                    await done_event.wait()

            except Exception as e:
                logger.error(f"TTS queue processing error: {e}")
            finally:
                if tmpfile:
                    try:
                        os.unlink(tmpfile)
                    except Exception:
                        pass
                queue.task_done()

    def _cleanup(self, guild_id: int):
        """Remove all TTS state for a guild and cancel the queue processor task."""
        self.active_channels.pop(guild_id, None)
        self.queues.pop(guild_id, None)
        task = self.queue_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()
        for key in list(self.rate_limits.keys()):
            if key[0] == guild_id:
                del self.rate_limits[key]

    @app_commands.command(name="join", description="Join this voice channel and read muted members' messages aloud")
    async def tts_join(self, interaction: discord.Interaction):
        """Join the current voice channel and start TTS.

        Must be used from a voice channel's text chat. The caller must be in
        the voice channel. Only one TTS session is allowed per guild at a time.
        """
        if not isinstance(interaction.channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "This command can only be used inside a voice channel's text chat!",
                ephemeral=True
            )
            return

        guild = interaction.guild
        if not guild:
            return
        channel: discord.VoiceChannel = interaction.channel

        if guild.id in self.active_channels:
            await interaction.response.send_message(
                "I'm already doing TTS in a voice channel! Use `/tts leave` first.",
                ephemeral=True
            )
            return

        if guild.voice_client:
            await interaction.response.send_message(
                "I'm already connected to a voice channel.",
                ephemeral=True
            )
            return

        if interaction.user not in channel.members:
            await interaction.response.send_message(
                "You need to be in this voice channel to start TTS!",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            await channel.connect(timeout=15.0, reconnect=False)
        except discord.ClientException as e:
            await interaction.followup.send(f"Failed to join the voice channel: `{e}`", ephemeral=True)
            return
        except Exception as e:
            logger.error(f"Failed to join VC {channel.id}: {e}")
            vc = guild.voice_client
            if isinstance(vc, discord.VoiceClient):
                await vc.disconnect(force=True)  # type: ignore[misc]
            await interaction.followup.send(
                f"Something went wrong trying to join the voice channel: `{e}`",
                ephemeral=True
            )
            return

        self.active_channels[guild.id] = channel.id
        queue: asyncio.Queue = asyncio.Queue()
        self.queues[guild.id] = queue
        self.queue_tasks[guild.id] = asyncio.create_task(self._process_queue(guild.id))
        logger.info(f"TTS started in guild {guild.id}, channel {channel.id}")

        await interaction.followup.send(
            "Joined! I'll read messages from muted members aloud. Use `/tts leave` to stop.\n"
            "-# Set a shorter TTS name with `/tts setnick`. Messages over 150 characters will be cut off."
        )

    @app_commands.command(name="leave", description="Leave the voice channel and stop TTS")
    async def tts_leave(self, interaction: discord.Interaction):
        """Disconnect from the voice channel and tear down TTS state for this guild."""
        guild = interaction.guild
        if not guild:
            return

        if guild.id not in self.active_channels:
            await interaction.response.send_message(
                "I'm not currently doing TTS in any voice channel!",
                ephemeral=True
            )
            return

        vc = guild.voice_client
        if isinstance(vc, discord.VoiceClient):
            await vc.disconnect()

        self._cleanup(guild.id)
        await interaction.response.send_message("Left the voice channel. TTS stopped!")

    @app_commands.command(name="setnick", description="Set a short TTS nickname for yourself. Anyone found misusing this will be punished.")
    @app_commands.describe(nickname="Your TTS nickname (max 32 characters)")
    async def tts_setnick(self, interaction: discord.Interaction, nickname: str):
        """Save a TTS nickname that will be read instead of the Discord username.

        URLs are stripped from the nickname to prevent misuse.
        """
        nickname = nickname.strip()
        if not nickname:
            await interaction.response.send_message("Nickname can't be empty!", ephemeral=True)
            return
        if len(nickname) > 32:
            await interaction.response.send_message("Nickname must be 32 characters or fewer.", ephemeral=True)
            return
        nickname = URL_PATTERN.sub('', nickname).strip()
        if not nickname:
            await interaction.response.send_message("That nickname isn't valid.", ephemeral=True)
            return

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO tts_nicks (user_id, nickname) VALUES (?, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET nickname = excluded.nickname",
                (interaction.user.id, nickname)
            )
            await db.commit()

        await interaction.response.send_message(f"TTS nickname set to **{nickname}**.", ephemeral=True)

    @app_commands.command(name="clearnick", description="Remove your TTS nickname and go back to your username")
    async def tts_clearnick(self, interaction: discord.Interaction):
        """Delete the saved TTS nickname so the Discord username is used again."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM tts_nicks WHERE user_id = ?", (interaction.user.id,))
            await db.commit()
        await interaction.response.send_message("TTS nickname cleared.", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        """Disconnect and clean up if all human members leave the active TTS channel."""
        if not self.bot.user or member.id == self.bot.user.id:
            return

        guild = member.guild
        if guild.id not in self.active_channels:
            return

        active_channel_id = self.active_channels[guild.id]
        if before.channel is None or before.channel.id != active_channel_id:
            return

        vc = guild.voice_client
        if not isinstance(vc, discord.VoiceClient):
            self._cleanup(guild.id)
            return

        human_members = [m for m in vc.channel.members if not m.bot]
        if not human_members:
            channel_id = self.active_channels.get(guild.id)
            await vc.disconnect()
            self._cleanup(guild.id)
            if channel_id:
                channel = guild.get_channel(channel_id)
                if isinstance(channel, discord.VoiceChannel):
                    try:
                        await channel.send("Everyone left, so I did too. TTS stopped!")
                    except Exception:
                        pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Queue a TTS entry for muted members' messages in the active voice channel chat."""
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        if guild_id not in self.active_channels:
            return
        if message.channel.id != self.active_channels[guild_id]:
            return

        if not isinstance(message.author, discord.Member):
            return

        voice_channel = message.guild.get_channel(self.active_channels[guild_id])
        if not isinstance(voice_channel, discord.VoiceChannel):
            return
        if message.author not in voice_channel.members:
            return

        voice_state = message.author.voice
        # Only read messages from users who are self-muted or server-muted
        if not voice_state or not (voice_state.self_mute or voice_state.mute):
            return

        # Skip slash/prefix commands — they'll already be handled by the bot
        if message.content.startswith('/') or message.content.startswith('!'):
            return

        now = time.monotonic()
        key = (guild_id, message.author.id)
        if now - self.rate_limits[key] < RATE_LIMIT_SECONDS:
            return
        self.rate_limits[key] = now

        content = message.content
        content = URL_PATTERN.sub('[link]', content)
        content = CUSTOM_EMOJI_PATTERN.sub(lambda m: m.group(1), content)
        content = content.strip()

        if not content:
            return

        if len(content) > MAX_MESSAGE_LENGTH:
            content = content[:MAX_MESSAGE_LENGTH] + ', message cut off'

        tts_name = await self._get_tts_name(message.author.id, message.author.name)

        queue = self.queues.get(guild_id)
        if queue:
            await queue.put((tts_name, content))


async def setup(bot: commands.Bot):
    await bot.add_cog(TTS(bot))
