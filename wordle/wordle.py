import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
import aiohttp
from embed.embed_color import get_embed_color
import os
import datetime
from pathlib import Path
from utils.logger import get_logger

logger = get_logger(__name__)

WORD_LIST_URL = "https://raw.githubusercontent.com/tabatkins/wordle-list/main/words"
WORDLE_DIR = "wordle"
WORD_LIST_PATH = os.path.join(WORDLE_DIR, "words.txt")
DB_PATH = Path(__file__).parent.parent / "data" / "wordle.db"

SQUARES = {"green": "🟩", "yellow": "🟨", "gray": "⬛"}

class Wordle(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        os.makedirs(WORDLE_DIR, exist_ok=True)

    async def cog_load(self):
        await self._init_db()
        await self._ensure_wordlist()

    async def _init_db(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS wordle_stats (
                    user_id INTEGER PRIMARY KEY,
                    played INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    current_streak INTEGER DEFAULT 0,
                    max_streak INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS wordle_games (
                    user_id INTEGER,
                    date TEXT,
                    guesses TEXT,
                    finished INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, date)
                )
            """)
            await db.commit()

    async def _ensure_wordlist(self):
        if not os.path.exists(WORD_LIST_PATH):
            async with aiohttp.ClientSession() as session:
                async with session.get(WORD_LIST_URL) as resp:
                    words = await resp.text()
            with open(WORD_LIST_PATH, "w", encoding="utf-8") as f:
                f.write(words)

        with open(WORD_LIST_PATH, "r", encoding="utf-8") as f:
            self.words = [w.strip() for w in f.read().splitlines() if len(w.strip()) == 5]
        logger.info(f"Loaded {len(self.words)} words.")

    def get_daily_word(self):
        today = datetime.date.today()
        index = today.toordinal() % len(self.words)
        return self.words[index]

    def compare_guess(self, guess, target):
        result = ["gray"] * 5
        target_chars = list(target)

        for i, ch in enumerate(guess):
            if ch == target[i]:
                result[i] = "green"
                target_chars[i] = None

        for i, ch in enumerate(guess):
            if result[i] == "gray" and ch in target_chars:
                result[i] = "yellow"
                target_chars[target_chars.index(ch)] = None

        return result

    def get_keyboard_display(self, guesses, target):
        keyboard_rows = [
            "qwertyuiop",
            "asdfghjkl",
            "zxcvbnm"
        ]

        letter_status = {}
        status_priority = {"green": 3, "yellow": 2, "gray": 1}

        for guess in guesses:
            result = self.compare_guess(guess, target)
            for ch, status in zip(guess, result):
                current_priority = status_priority.get(letter_status.get(ch), 0)
                new_priority = status_priority[status]
                if new_priority > current_priority:
                    letter_status[ch] = status

        display_lines = []
        for row in keyboard_rows:
            row_display = []
            for letter in row:
                if letter in letter_status:
                    status = letter_status[letter]
                    if status == "green":
                        row_display.append(f"{letter.upper()}🟩")
                    elif status == "yellow":
                        row_display.append(f"{letter.upper()}🟨")
                    else:
                        row_display.append(f"{letter.upper()}⬛")
                else:
                    row_display.append(f"{letter.upper()}⬜")
            display_lines.append(" ".join(row_display))

        return "\n".join(display_lines)

    async def get_user_game(self, user_id):
        today = str(datetime.date.today())
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT guesses, finished FROM wordle_games WHERE user_id=? AND date=?", (user_id, today))
            return await cursor.fetchone()

    async def update_user_game(self, user_id, guesses, finished):
        today = str(datetime.date.today())
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO wordle_games (user_id, date, guesses, finished)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, date) DO UPDATE SET guesses=excluded.guesses, finished=excluded.finished
            """, (user_id, today, guesses, finished))
            await db.commit()

    async def update_stats(self, user_id, win):
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT played, wins, current_streak, max_streak FROM wordle_stats WHERE user_id=?", (user_id,))
            row = await cursor.fetchone()

            if not row:
                played, wins, streak, max_streak = 0, 0, 0, 0
            else:
                played, wins, streak, max_streak = row

            played += 1
            if win:
                wins += 1
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0

            await db.execute("""
                INSERT INTO wordle_stats (user_id, played, wins, current_streak, max_streak)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET played=excluded.played, wins=excluded.wins,
                current_streak=excluded.current_streak, max_streak=excluded.max_streak
            """, (user_id, played, wins, streak, max_streak))
            await db.commit()

    async def handle_guess(self, interaction, guess):
        if len(guess) != 5 or guess not in self.words:
            await interaction.response.send_message("That's not a valid word.", ephemeral=True)
            return

        user_id = interaction.user.id
        target = self.get_daily_word()
        row = await self.get_user_game(user_id)

        guesses = [] if not row else (row[0].split(",") if row[0] else [])
        finished = row[1] if row else 0

        if finished:
            await interaction.response.send_message("You've already finished today's Wordle!", ephemeral=True)
            return

        guesses.append(guess)
        result = self.compare_guess(guess, target)

        if guess == target:
            await self.update_user_game(user_id, ",".join(guesses), 1)
            await self.update_stats(user_id, True)
            await interaction.response.send_message(f"✅ You got it! Wordle {datetime.date.today()} solved in {len(guesses)} tries.", ephemeral=True)

            embed = discord.Embed(
                title=f"{interaction.user.display_name}'s Wordle {datetime.date.today()} Result",
                description="\n".join(["".join(SQUARES[c] for c in self.compare_guess(g, target)) for g in guesses]),
                color=get_embed_color(interaction.user.id)
            )
            await interaction.channel.send(embed=embed)
            return

        if len(guesses) >= 6:
            await self.update_user_game(user_id, ",".join(guesses), 1)
            await self.update_stats(user_id, False)
            await interaction.response.send_message(f"❌ You've used all 6 guesses. The word was **{target.upper()}**.", ephemeral=True)

            embed = discord.Embed(
                title=f"{interaction.user.display_name}'s Wordle {datetime.date.today()} Result",
                description="\n".join(["".join(SQUARES[c] for c in self.compare_guess(g, target)) for g in guesses]),
                color=get_embed_color(interaction.user.id)
            )
            await interaction.channel.send(embed=embed)
            return

        await self.update_user_game(user_id, ",".join(guesses), 0)

        grid_lines = []
        for g in guesses:
            squares = "".join(SQUARES[c] for c in self.compare_guess(g, target))
            grid_lines.append(f"{squares}  `{g.upper()}`")
        grid = "\n".join(grid_lines)

        keyboard = self.get_keyboard_display(guesses, target)
        await interaction.response.send_message(
            f"Your guesses so far:\n{grid}\n\nGuesses: {len(guesses)}/6\n\n**Keyboard:**\n{keyboard}",
            ephemeral=True
        )

    @app_commands.command(name="wordle", description="Start today's Wordle game.")
    async def wordle(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        row = await self.get_user_game(user_id)

        if row and row[1]:
            await interaction.response.send_message("You've already finished today's Wordle! Check back tomorrow.", ephemeral=True)
            return

        guesses = [] if not row else (row[0].split(",") if row[0] else [])

        if guesses:
            target = self.get_daily_word()

            grid_lines = []
            for g in guesses:
                squares = "".join(SQUARES[c] for c in self.compare_guess(g, target))
                grid_lines.append(f"{squares}  `{g.upper()}`")
            grid = "\n".join(grid_lines)

            keyboard = self.get_keyboard_display(guesses, target)
            await interaction.response.send_message(
                f"You have a game in progress! Use `/wordle_guess <word>` to continue.\n\n{grid}\n\nGuesses: {len(guesses)}/6\n\n**Keyboard:**\n{keyboard}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"🎮 Started Wordle for {datetime.date.today()}!\n\nUse `/wordle_guess <word>` to make your guesses. You have 6 tries!",
                ephemeral=True
            )

    @app_commands.command(name="wordle_guess", description="Submit a guess for today's Wordle.")
    @app_commands.describe(guess="Your 5-letter word guess")
    async def wordle_guess(self, interaction: discord.Interaction, guess: str):
        await self.handle_guess(interaction, guess.lower())

    @app_commands.command(name="wordle_stats", description="View your Wordle stats.")
    async def wordle_stats(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT played, wins, current_streak, max_streak FROM wordle_stats WHERE user_id=?", (user_id,))
            row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message("You haven't played any games yet!", ephemeral=True)
            return

        played, wins, streak, max_streak = row
        win_rate = (wins / played * 100) if played else 0

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT guesses FROM wordle_games WHERE user_id=? AND finished=1", (user_id,))
            rows = await cursor.fetchall()

        avg_guesses = 0
        if rows:
            valid = [len(r[0].split(",")) for r in rows if r[0]]
            avg_guesses = round(sum(valid) / len(valid), 2) if valid else 0

        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Wordle Stats",
            color=get_embed_color(interaction.user.id)
        )
        embed.add_field(name="Games Played", value=str(played))
        embed.add_field(name="Wins", value=str(wins))
        embed.add_field(name="Win Rate", value=f"{win_rate:.1f}%")
        embed.add_field(name="Current Streak", value=str(streak))
        embed.add_field(name="Max Streak", value=str(max_streak))
        embed.add_field(name="Average Guesses", value=str(avg_guesses))
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="wordle_serverstats", description="View server-wide Wordle stats.")
    async def wordle_serverstats(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT played, wins FROM wordle_stats")
            stats_rows = await cursor.fetchall()
            cursor = await db.execute("SELECT guesses FROM wordle_games WHERE finished=1")
            guess_rows = await cursor.fetchall()

        total_played = sum(r[0] for r in stats_rows)
        total_wins = sum(r[1] for r in stats_rows)
        total_losses = total_played - total_wins
        win_rate = (total_wins / total_played * 100) if total_played else 0

        guesses = [len(r[0].split(",")) for r in guess_rows if r[0]]
        avg_guesses = round(sum(guesses) / len(guesses), 2) if guesses else 0

        embed = discord.Embed(
            title="Server Wordle Stats",
            color=get_embed_color(interaction.user.id)
        )
        embed.add_field(name="Total Games Played", value=str(total_played))
        embed.add_field(name="Total Wins", value=str(total_wins))
        embed.add_field(name="Total Losses", value=str(total_losses))
        embed.add_field(name="Overall Win Rate", value=f"{win_rate:.1f}%")
        embed.add_field(name="Average Guesses (Wins)", value=str(avg_guesses))

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Wordle(bot))
