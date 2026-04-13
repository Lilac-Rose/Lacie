import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import aiosqlite
from pathlib import Path
from typing import Optional
from embed.embed_color import get_embed_color
import re
from datetime import datetime, timedelta
from utils.logger import get_logger

logger = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "minesweeper.db"


async def _update_stats(user_id: int, win: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS minesweeper_stats (
                user_id INTEGER PRIMARY KEY,
                played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                current_streak INTEGER DEFAULT 0,
                max_streak INTEGER DEFAULT 0
            )
        """)
        cursor = await db.execute(
            "SELECT played, wins, current_streak, max_streak FROM minesweeper_stats WHERE user_id=?",
            (user_id,)
        )
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
            INSERT INTO minesweeper_stats (user_id, played, wins, current_streak, max_streak)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                played=excluded.played, wins=excluded.wins,
                current_streak=excluded.current_streak, max_streak=excluded.max_streak
        """, (user_id, played, wins, streak, max_streak))
        await db.commit()

class MinesweeperGame:
    def __init__(self, rows: int = 13, cols: int = 13, mines: int = 20):
        self.rows = rows
        self.cols = cols
        self.mine_count = mines

        # Board: -1 = mine, 0-8 = number of adjacent mines
        self.board = [[0 for _ in range(cols)] for _ in range(rows)]
        self.revealed = [[False for _ in range(cols)] for _ in range(rows)]
        self.flags = [[False for _ in range(cols)] for _ in range(rows)]

        self.game_over = False
        self.won = False
        self.first_move = True

        # 11-13 use custom bot emojis
        self.col_emojis = [
            "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟",
            "<:11:1470841923785719952>",
            "<:12:1470841922716172299>",
            "<:13:1470841927409729600>"
        ]

    def setup_board(self, safe_row: int, safe_col: int):
        positions = [(r, c) for r in range(self.rows) for c in range(self.cols)
                     if not (abs(r - safe_row) <= 1 and abs(c - safe_col) <= 1)]

        mine_positions = random.sample(positions, self.mine_count)

        for r, c in mine_positions:
            self.board[r][c] = -1

        for r in range(self.rows):
            for c in range(self.cols):
                if self.board[r][c] != -1:
                    count = 0
                    for dr in [-1, 0, 1]:
                        for dc in [-1, 0, 1]:
                            if dr == 0 and dc == 0:
                                continue
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < self.rows and 0 <= nc < self.cols:
                                if self.board[nr][nc] == -1:
                                    count += 1
                    self.board[r][c] = count

    def reveal(self, row: int, col: int) -> bool:
        if self.first_move:
            self.setup_board(row, col)
            self.first_move = False

        if self.revealed[row][col] or self.flags[row][col]:
            return False

        self.revealed[row][col] = True

        if self.board[row][col] == -1:
            self.game_over = True
            return True

        if self.board[row][col] == 0:
            self._flood_fill(row, col)

        if self.check_win():
            self.game_over = True
            self.won = True

        return False

    def _flood_fill(self, start_row: int, start_col: int):
        from collections import deque

        queue = deque([(start_row, start_col)])
        visited = set()
        visited.add((start_row, start_col))

        while queue:
            row, col = queue.popleft()

            for dr in [-1, 0, 1]:
                for dc in [-1, 0, 1]:
                    if dr == 0 and dc == 0:
                        continue

                    nr, nc = row + dr, col + dc

                    if not (0 <= nr < self.rows and 0 <= nc < self.cols):
                        continue
                    if (nr, nc) in visited:
                        continue
                    if self.flags[nr][nc]:
                        continue

                    visited.add((nr, nc))
                    self.revealed[nr][nc] = True

                    if self.board[nr][nc] == 0:
                        queue.append((nr, nc))

    def toggle_flag(self, row: int, col: int):
        if self.revealed[row][col]:
            return
        self.flags[row][col] = not self.flags[row][col]

    def check_win(self) -> bool:
        for r in range(self.rows):
            for c in range(self.cols):
                if self.board[r][c] != -1 and not self.revealed[r][c]:
                    return False
        return True

    def get_cell_display(self, row: int, col: int, show_all: bool = False) -> str:
        if show_all and self.board[row][col] == -1:
            return "💣"

        if self.flags[row][col]:
            return "🚩"

        if not self.revealed[row][col]:
            return "⬛"

        if self.board[row][col] == -1:
            return "💥"

        num_to_emoji = {
            0: "⬜",
            1: "1️⃣",
            2: "2️⃣",
            3: "3️⃣",
            4: "4️⃣",
            5: "5️⃣",
            6: "6️⃣",
            7: "7️⃣",
            8: "8️⃣"
        }
        return num_to_emoji.get(self.board[row][col], "⬜")

    def render_board(self) -> str:
        col_headers = "⬛" + "".join(self.col_emojis[:self.cols])

        lines = [col_headers]
        for r in range(self.rows):
            row_header = chr(0x1F1E6 + r)  # regional indicator A-M
            row_str = row_header + "".join(
                self.get_cell_display(r, c, self.game_over)
                for c in range(self.cols)
            )
            lines.append(row_str)

        return "\n".join(lines)

    def get_stats(self) -> str:
        total_flags = sum(sum(row) for row in self.flags)
        cells_remaining = sum(
            1 for r in range(self.rows)
            for c in range(self.cols)
            if not self.revealed[r][c] and self.board[r][c] != -1
        )

        return f"🚩 Flags: {total_flags}/{self.mine_count} | 💣 Mines: {self.mine_count} | ⬛ Cells left: {cells_remaining}"


class MinesweeperView(discord.ui.View):
    def __init__(self, player: discord.Member, game: MinesweeperGame):
        super().__init__(timeout=None)  # timeout handled manually
        self.player = player
        self.game = game
        self.message: Optional[discord.Message] = None
        self.timeout_seconds = 1800  # 30 minutes
        self.timeout_task = None
        self.timed_out = False

    async def start_timeout(self):
        if self.timeout_task and not self.timeout_task.done():
            self.timeout_task.cancel()
        self.timeout_task = asyncio.create_task(self._timeout_handler())

    async def _timeout_handler(self):
        try:
            await asyncio.sleep(self.timeout_seconds)
            await self.handle_timeout()
        except asyncio.CancelledError:
            pass

    async def handle_timeout(self):
        if self.timed_out or self.game.game_over:
            return

        self.timed_out = True
        self.game.game_over = True
        await _update_stats(self.player.id, False)

        for child in self.children:
            child.disabled = True

        self.stop()

        if self.message:
            embed = self.create_embed()
            embed.color = discord.Color.orange()
            embed.title = "⏱️ Game Timed Out"
            embed.description = f"{self.player.mention}'s game has ended due to inactivity (30 minutes)."
            embed.set_footer(text="The game has been automatically closed.")
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.errors.NotFound:
                # message was deleted
                pass
            except Exception as e:
                logger.error(f"Error updating timed out game: {e}")

    def reset_timeout(self):
        if not self.game.game_over and not self.timed_out:
            asyncio.create_task(self.start_timeout())

    @discord.ui.button(label="Forfeit", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def forfeit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("Only the player can forfeit!", ephemeral=True)
            return

        self.game.game_over = True

        if self.timeout_task and not self.timeout_task.done():
            self.timeout_task.cancel()

        for child in self.children:
            child.disabled = True
        self.stop()
        await _update_stats(self.player.id, False)

        embed = self.create_embed()
        embed.color = discord.Color.red()
        embed.title = "💀 Game Over - Forfeited"

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="How to Play", style=discord.ButtonStyle.secondary, emoji="❓")
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        help_embed = discord.Embed(
            title="🎮 How to Play Minesweeper",
            description="Send messages in this channel to make moves!",
            color=get_embed_color(interaction.user.id)
        )
        help_embed.add_field(
            name="📝 Move Format",
            value="```[column] [row] [flag]```",
            inline=False
        )
        help_embed.add_field(
            name="Examples",
            value=(
                "• `1 A` - Reveal cell at column 1, row A\n"
                "• `6 B F` - Flag cell at column 6, row B\n"
                "• `7D FLAG` - Flag cell at column 7, row D\n"
                "• `2Hf` - Flag cell at column 2, row H"
            ),
            inline=False
        )
        help_embed.add_field(
            name="📌 Notes",
            value=(
                "• Column: 1-13 (numbers)\n"
                "• Row: A-M (letters)\n"
                "• Flag: f, flag, or leave blank\n"
                "• Inputs are NOT case sensitive!\n"
                "• Your messages will be auto-deleted"
            ),
            inline=False
        )

        await interaction.response.send_message(embed=help_embed, ephemeral=True)

    def create_embed(self) -> discord.Embed:
        if self.game.game_over:
            if self.game.won:
                embed = discord.Embed(
                    title="🎉 You Win!",
                    description=f"{self.player.mention} successfully cleared the minefield!",
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title="💥 Game Over!",
                    description=f"{self.player.mention} hit a mine!",
                    color=discord.Color.red()
                )
        else:
            embed = discord.Embed(
                title="💣 Minesweeper",
                description=f"{self.player.mention}'s game",
                color=get_embed_color(self.player.id)
            )

        board = self.game.render_board()
        # Discord embed fields max out around 1024 chars, board can get big
        if len(board) < 1900:
            embed.add_field(name="Board", value=board, inline=False)
        else:
            lines = board.split('\n')
            chunk_size = len(lines) // 2
            chunk1 = '\n'.join(lines[:chunk_size])
            chunk2 = '\n'.join(lines[chunk_size:])
            embed.add_field(name="Board (1/2)", value=chunk1, inline=False)
            embed.add_field(name="Board (2/2)", value=chunk2, inline=False)

        stats = self.game.get_stats()
        embed.add_field(name="Stats", value=stats, inline=False)

        if not self.game.game_over:
            embed.set_footer(text="Send your move in chat: [column number] [row letter] [flag] | Timeout resets with each move (30min)")

        return embed


class Minesweeper(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {}  # channel_id: (player_id, MinesweeperView)

    @app_commands.command(name="minesweeper", description="Start a game of Minesweeper")
    @app_commands.describe(
        difficulty="Choose difficulty level (Easy: 13x13 with 20 mines, Medium: 13x13 with 35 mines, Hard: 13x13 with 50 mines)"
    )
    @app_commands.choices(difficulty=[
        app_commands.Choice(name="Easy (20 mines)", value=1),
        app_commands.Choice(name="Medium (35 mines)", value=2),
        app_commands.Choice(name="Hard (50 mines)", value=3)
    ])
    async def minesweeper(self, interaction: discord.Interaction, difficulty: int = 1):
        if interaction.channel_id in self.active_games:
            await interaction.response.send_message(
                f"There's already an active game in this channel! Please wait for it to finish.",
                ephemeral=True
            )
            return

        mine_counts = {1: 20, 2: 35, 3: 50}
        mines = mine_counts.get(difficulty, 20)

        await interaction.response.defer()

        if not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
            return

        game = MinesweeperGame(rows=13, cols=13, mines=mines)
        view = MinesweeperView(interaction.user, game)

        embed = view.create_embed()
        message = await interaction.followup.send(embed=embed, view=view)
        view.message = message

        await view.start_timeout()

        self.active_games[interaction.channel_id] = (interaction.user.id, view)

        await view.wait()

        if interaction.channel_id in self.active_games:
            del self.active_games[interaction.channel_id]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if message.channel.id not in self.active_games:
            return

        player_id, view = self.active_games[message.channel.id]

        if message.author.id != player_id:
            return

        if view.game.game_over:
            return

        move = self.parse_move(message.content)

        if move is None:
            # not a move attempt, leave the message alone
            return

        col, row, is_flag = move

        try:
            await message.delete()
        except Exception:
            pass

        if is_flag:
            view.game.toggle_flag(row, col)
        else:
            view.game.reveal(row, col)

        view.reset_timeout()

        if view.game.game_over:
            if view.timeout_task and not view.timeout_task.done():
                view.timeout_task.cancel()

            await _update_stats(player_id, view.game.won)

            for child in view.children:
                child.disabled = True
            view.stop()

        embed = view.create_embed()
        try:
            await view.message.edit(embed=embed, view=view)
        except Exception:
            pass

    def parse_move(self, text: str) -> tuple[int, int, bool] | None:
        text = text.upper().strip()

        pattern = r'(\d+)\s*([A-M])\s*(F|FLAG)?'
        match = re.match(pattern, text)

        if not match:
            return None

        col_str, row_letter, flag = match.groups()

        col = int(col_str) - 1
        row = ord(row_letter) - ord('A')

        if not (0 <= col < 13 and 0 <= row < 13):
            return None

        is_flag = flag is not None

        return (col, row, is_flag)


    @app_commands.command(name="minesweeper_stats", description="View your Minesweeper stats")
    async def minesweeper_stats(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS minesweeper_stats (
                    user_id INTEGER PRIMARY KEY,
                    played INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    current_streak INTEGER DEFAULT 0,
                    max_streak INTEGER DEFAULT 0
                )
            """)
            cursor = await db.execute(
                "SELECT played, wins, current_streak, max_streak FROM minesweeper_stats WHERE user_id=?",
                (user_id,)
            )
            row = await cursor.fetchone()

        if not row or row[0] == 0:
            await interaction.response.send_message("You haven't played Minesweeper yet!", ephemeral=True)
            return

        played, wins, streak, max_streak = row
        losses = played - wins
        win_rate = round(wins / played * 100, 1) if played else 0

        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Minesweeper Stats",
            color=get_embed_color(user_id)
        )
        embed.add_field(name="Games Played", value=str(played))
        embed.add_field(name="Wins", value=str(wins))
        embed.add_field(name="Losses", value=str(losses))
        embed.add_field(name="Win Rate", value=f"{win_rate}%")
        embed.add_field(name="Current Streak", value=str(streak))
        embed.add_field(name="Best Streak", value=str(max_streak))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="minesweeper_serverstats", description="View server-wide Minesweeper stats")
    async def minesweeper_serverstats(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT played, wins FROM minesweeper_stats")
            rows = await cursor.fetchall()

        if not rows:
            await interaction.response.send_message("Nobody has played Minesweeper yet!", ephemeral=True)
            return

        total_played = sum(r[0] for r in rows)
        total_wins = sum(r[1] for r in rows)
        total_losses = total_played - total_wins
        win_rate = round(total_wins / total_played * 100, 1) if total_played else 0

        embed = discord.Embed(
            title="Server Minesweeper Stats",
            color=get_embed_color(interaction.user.id)
        )
        embed.add_field(name="Total Games Played", value=str(total_played))
        embed.add_field(name="Total Wins", value=str(total_wins))
        embed.add_field(name="Total Losses", value=str(total_losses))
        embed.add_field(name="Overall Win Rate", value=f"{win_rate}%")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Minesweeper(bot))
