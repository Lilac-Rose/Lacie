import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import re

class MinesweeperGame:
    def __init__(self, rows: int = 13, cols: int = 13, mines: int = 20):
        self.rows = rows
        self.cols = cols
        self.mine_count = mines
        
        # Board: -1 = mine, 0-8 = number of adjacent mines
        self.board = [[0 for _ in range(cols)] for _ in range(rows)]
        # Revealed: False = hidden, True = revealed
        self.revealed = [[False for _ in range(cols)] for _ in range(rows)]
        # Flags: False = no flag, True = flagged
        self.flags = [[False for _ in range(cols)] for _ in range(rows)]
        
        self.game_over = False
        self.won = False
        self.first_move = True
        
        # Column number emojis (11-13 use custom bot emojis)
        self.col_emojis = [
            "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟",
            "<:11:1470841923785719952>",
            "<:12:1470841922716172299>",
            "<:13:1470841927409729600>"
        ]
        
    def setup_board(self, safe_row: int, safe_col: int):
        """Generate mines avoiding the first click position"""
        positions = [(r, c) for r in range(self.rows) for c in range(self.cols)
                     if not (abs(r - safe_row) <= 1 and abs(c - safe_col) <= 1)]
        
        mine_positions = random.sample(positions, self.mine_count)
        
        for r, c in mine_positions:
            self.board[r][c] = -1
        
        # Calculate numbers
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
        """Reveal a cell. Returns True if hit a mine."""
        if self.first_move:
            self.setup_board(row, col)
            self.first_move = False
        
        if self.revealed[row][col] or self.flags[row][col]:
            return False
        
        self.revealed[row][col] = True
        
        if self.board[row][col] == -1:
            self.game_over = True
            return True
        
        # Flood fill: Auto-reveal adjacent cells if it's a 0
        if self.board[row][col] == 0:
            self._flood_fill(row, col)
        
        # Check win condition
        if self.check_win():
            self.game_over = True
            self.won = True
        
        return False
    
    def _flood_fill(self, start_row: int, start_col: int):
        """
        Flood fill algorithm to reveal all connected empty cells and their borders.
        Reveals all 0-cells connected to the starting position, plus the numbered
        cells that border them (the 'edge' of the empty region).
        """
        from collections import deque
        
        queue = deque([(start_row, start_col)])
        visited = set()
        visited.add((start_row, start_col))
        
        while queue:
            row, col = queue.popleft()
            
            # Check all 8 adjacent cells
            for dr in [-1, 0, 1]:
                for dc in [-1, 0, 1]:
                    if dr == 0 and dc == 0:
                        continue
                    
                    nr, nc = row + dr, col + dc
                    
                    # Skip if out of bounds or already visited
                    if not (0 <= nr < self.rows and 0 <= nc < self.cols):
                        continue
                    if (nr, nc) in visited:
                        continue
                    
                    # Skip if flagged
                    if self.flags[nr][nc]:
                        continue
                    
                    # Mark as visited
                    visited.add((nr, nc))
                    
                    # Reveal the cell
                    self.revealed[nr][nc] = True
                    
                    # If it's also a 0, add it to the queue to continue flood fill
                    if self.board[nr][nc] == 0:
                        queue.append((nr, nc))
    
    def toggle_flag(self, row: int, col: int):
        """Toggle flag on a cell"""
        if self.revealed[row][col]:
            return
        self.flags[row][col] = not self.flags[row][col]
    
    def check_win(self) -> bool:
        """Check if all non-mine cells are revealed"""
        for r in range(self.rows):
            for c in range(self.cols):
                if self.board[r][c] != -1 and not self.revealed[r][c]:
                    return False
        return True
    
    def get_cell_display(self, row: int, col: int, show_all: bool = False) -> str:
        """Get the display string for a cell"""
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
        """Render the board as a string"""
        # Column headers using numbers
        col_headers = "⬛" + "".join(self.col_emojis[:self.cols])
        
        lines = [col_headers]
        for r in range(self.rows):
            # Row headers using letters (A-M)
            row_header = chr(0x1F1E6 + r)  # Regional indicator A-M
            row_str = row_header + "".join(
                self.get_cell_display(r, c, self.game_over)
                for c in range(self.cols)
            )
            lines.append(row_str)
        
        return "\n".join(lines)
    
    def get_stats(self) -> str:
        """Get game statistics"""
        total_flags = sum(sum(row) for row in self.flags)
        flags_remaining = self.mine_count - total_flags
        cells_remaining = sum(
            1 for r in range(self.rows) 
            for c in range(self.cols) 
            if not self.revealed[r][c] and self.board[r][c] != -1
        )
        
        return f"🚩 Flags: {total_flags}/{self.mine_count} | 💣 Mines: {self.mine_count} | ⬛ Cells left: {cells_remaining}"


class MinesweeperView(discord.ui.View):
    def __init__(self, player: discord.Member, game: MinesweeperGame):
        super().__init__(timeout=600)
        self.player = player
        self.game = game
        self.message: discord.Message = None
    
    @discord.ui.button(label="Forfeit", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def forfeit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("Only the player can forfeit!", ephemeral=True)
            return
        
        self.game.game_over = True
        for child in self.children:
            child.disabled = True
        self.stop()
        
        embed = self.create_embed()
        embed.color = discord.Color.red()
        embed.title = "💀 Game Over - Forfeited"
        
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="How to Play", style=discord.ButtonStyle.secondary, emoji="❓")
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        help_embed = discord.Embed(
            title="🎮 How to Play Minesweeper",
            description="Send messages in this channel to make moves!",
            color=discord.Color.blue()
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
        """Create the game embed"""
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
                color=discord.Color.blue()
            )
        
        board = self.game.render_board()
        # Discord has a 4096 character limit for embed descriptions
        # Split board if needed
        if len(board) < 1900:
            embed.add_field(name="Board", value=board, inline=False)
        else:
            # Split into chunks
            lines = board.split('\n')
            chunk_size = len(lines) // 2
            chunk1 = '\n'.join(lines[:chunk_size])
            chunk2 = '\n'.join(lines[chunk_size:])
            embed.add_field(name="Board (1/2)", value=chunk1, inline=False)
            embed.add_field(name="Board (2/2)", value=chunk2, inline=False)
        
        stats = self.game.get_stats()
        embed.add_field(name="Stats", value=stats, inline=False)
        
        if not self.game.game_over:
            embed.set_footer(text="Send your move in chat: [column number] [row letter] [flag]")
        
        return embed
    
    async def on_timeout(self):
        self.game.game_over = True
        for child in self.children:
            child.disabled = True
        
        if self.message:
            embed = self.create_embed()
            embed.color = discord.Color.greyple()
            embed.title = "⏱️ Game Timed Out"
            try:
                await self.message.edit(embed=embed, view=self)
            except:
                pass


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
        # Check if there's already an active game in this channel
        if interaction.channel_id in self.active_games:
            player_id, _ = self.active_games[interaction.channel_id]
            await interaction.response.send_message(
                f"There's already an active game in this channel! Please wait for it to finish.",
                ephemeral=True
            )
            return
        
        # Set difficulty
        mine_counts = {1: 20, 2: 35, 3: 50}
        mines = mine_counts.get(difficulty, 20)
        
        await interaction.response.defer()
        
        game = MinesweeperGame(rows=13, cols=13, mines=mines)
        view = MinesweeperView(interaction.user, game)
        
        embed = view.create_embed()
        message = await interaction.followup.send(embed=embed, view=view)
        view.message = message
        
        self.active_games[interaction.channel_id] = (interaction.user.id, view)
        
        # Wait for the game to finish
        await view.wait()
        
        # Clean up
        if interaction.channel_id in self.active_games:
            del self.active_games[interaction.channel_id]
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Check if there's an active game in this channel
        if message.channel.id not in self.active_games:
            return
        
        player_id, view = self.active_games[message.channel.id]
        
        # Check if message is from the player
        if message.author.id != player_id:
            return
        
        # Check if game is over
        if view.game.game_over:
            return
        
        # Parse the message
        move = self.parse_move(message.content)
        
        if move is None:
            # Invalid format, don't delete the message - it's not an input attempt
            return
        
        col, row, is_flag = move
        
        # Valid input - delete the player's message to reduce clutter
        try:
            await message.delete()
        except:
            pass
        
        # Make the move
        if is_flag:
            view.game.toggle_flag(row, col)
        else:
            view.game.reveal(row, col)
        
        # Update the embed
        if view.game.game_over:
            for child in view.children:
                child.disabled = True
            view.stop()
        
        embed = view.create_embed()
        try:
            await view.message.edit(embed=embed, view=view)
        except:
            pass
    
    def parse_move(self, text: str) -> tuple[int, int, bool] | None:
        """
        Parse a move from text.
        Returns (col, row, is_flag) or None if invalid.
        Format: [column number] [row letter] [flag]
        Examples: "1 A", "6 B F", "7D FLAG", "2Hf"
        """
        text = text.upper().strip()
        
        # Try to match pattern with optional spaces and flag
        # Pattern: number (1-13), letter (A-M), optional flag
        pattern = r'(\d+)\s*([A-M])\s*(F|FLAG)?'
        match = re.match(pattern, text)
        
        if not match:
            return None
        
        col_str, row_letter, flag = match.groups()
        
        col = int(col_str) - 1  # Convert to 0-indexed
        row = ord(row_letter) - ord('A')  # Convert letter to 0-indexed number
        
        # Validate
        if not (0 <= col < 13 and 0 <= row < 13):
            return None
        
        is_flag = flag is not None
        
        return (col, row, is_flag)


async def setup(bot):
    await bot.add_cog(Minesweeper(bot))