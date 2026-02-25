import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import traceback

EMPTY = "⚪"
RED = "🔴"
YELLOW = "🟡"

class ColumnButton(discord.ui.Button):
    def __init__(self, col: int):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=str(col + 1)
        )
        self.col = col

    async def callback(self, interaction: discord.Interaction):
        view: Connect4View = self.view  # type: ignore

        if interaction.user.id not in (view.player1.id, view.player2.id):
            await interaction.response.send_message("You're not part of this game.", ephemeral=True)
            return

        if interaction.user.id != view.current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        row_index = view.get_drop_row(self.col)
        if row_index is None:
            await interaction.response.send_message("That column is full!", ephemeral=True)
            return

        mark = view.current_mark
        view.board[row_index][self.col] = mark

        winner = view.check_winner()
        board_str = view.render_board()

        if winner:
            for child in view.children:
                child.disabled = True
            view.stop()

            if winner == 3:
                await interaction.response.edit_message(content=f"{board_str}\nIt's a tie! 🤝", view=view)
            else:
                winner_user = view.player1 if winner == 1 else view.player2
                await interaction.response.edit_message(content=f"{board_str}\n{winner_user.mention} wins! 🎉", view=view)
            return

        view.current_mark = 2 if view.current_mark == 1 else 1
        view.current_player = view.player2 if view.current_mark == 2 else view.player1
        view.current_symbol = RED if view.current_mark == 1 else YELLOW

        await interaction.response.edit_message(
            content=f"{board_str}\n{view.current_player.mention}'s turn ({view.current_symbol})",
            view=view
        )


class Connect4View(discord.ui.View):
    def __init__(self, player1: discord.Member, player2: discord.Member, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.player1 = player1
        self.player2 = player2

        self.board = [[0 for _ in range(7)] for _ in range(6)]
        self.current_mark = 1
        self.current_player = player1
        self.current_symbol = RED

        # 7 buttons: 5 in first row, 2 in second row (Discord's 5-button limit per row)
        for col in range(7):
            btn = ColumnButton(col)
            btn.row = 0 if col < 5 else 1
            self.add_item(btn)

    def get_drop_row(self, col: int):
        for r in range(5, -1, -1):
            if self.board[r][col] == 0:
                return r
        return None

    def render_board(self) -> str:
        lines = []
        for r in range(6):
            line = "".join(
                RED if self.board[r][c] == 1 else
                YELLOW if self.board[r][c] == 2 else
                EMPTY
                for c in range(7)
            )
            lines.append(line)
        footer = "1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣"
        return "\n".join(lines) + "\n" + footer

    def check_winner(self):
        B = self.board
        ROWS, COLS = 6, 7

        for r in range(ROWS):
            for c in range(COLS - 3):
                v = B[r][c]
                if v != 0 and v == B[r][c + 1] == B[r][c + 2] == B[r][c + 3]:
                    return v

        for r in range(ROWS - 3):
            for c in range(COLS):
                v = B[r][c]
                if v != 0 and v == B[r + 1][c] == B[r + 2][c] == B[r + 3][c]:
                    return v

        for r in range(ROWS - 3):
            for c in range(COLS - 3):
                v = B[r][c]
                if v != 0 and v == B[r + 1][c + 1] == B[r + 2][c + 2] == B[r + 3][c + 3]:
                    return v

        for r in range(ROWS - 3):
            for c in range(3, COLS):
                v = B[r][c]
                if v != 0 and v == B[r + 1][c - 1] == B[r + 2][c - 2] == B[r + 3][c - 3]:
                    return v

        if all(B[r][c] != 0 for r in range(ROWS) for c in range(COLS)):
            return 3

        return None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        self.stop()


class ConfirmView(discord.ui.View):
    def __init__(self, challenged: discord.Member):
        super().__init__(timeout=60)
        self.challenged = challenged
        self.value = None

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.challenged.id:
            await interaction.response.send_message("Only the challenged player can accept!", ephemeral=True)
            return
        self.value = True
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.challenged.id:
            await interaction.response.send_message("Only the challenged player can decline!", ephemeral=True)
            return
        self.value = False
        self.stop()


class Connect4(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="connect4", description="Start a game of Connect Four with another user")
    @app_commands.describe(user="The user you want to play against")
    async def connect4(self, interaction: discord.Interaction, user: discord.Member):
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't play against yourself!", ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message("You can't play against a bot!", ephemeral=True)
            return

        confirm_view = ConfirmView(user)
        await interaction.response.send_message(
            f"{user.mention}, {interaction.user.mention} has challenged you to Connect Four! Do you accept?",
            view=confirm_view
        )

        await confirm_view.wait()

        if confirm_view.value is None:
            await interaction.edit_original_response(
                content=f"{user.mention} didn't respond in time. Game cancelled.",
                view=None
            )
            return
        if not confirm_view.value:
            await interaction.edit_original_response(
                content=f"{user.mention} declined the challenge.",
                view=None
            )
            return

        await interaction.edit_original_response(content="Challenge accepted! Starting game...", view=None)

        try:
            game_view = Connect4View(interaction.user, user)

            if random.choice([True, False]):
                game_view.current_player = user
                game_view.current_mark = 2
                game_view.current_symbol = YELLOW
            else:
                game_view.current_player = interaction.user
                game_view.current_mark = 1
                game_view.current_symbol = RED

            board_str = game_view.render_board()

            await interaction.followup.send(
                content=f"{board_str}\nGame started! {game_view.current_player.mention} goes first ({game_view.current_symbol})",
                view=game_view
            )

        except Exception as e:
            err = "".join(traceback.format_exception_only(type(e), e)).strip()
            await interaction.edit_original_response(
                content=f"❌ An error occurred while starting the game:\n```{err}```",
                view=None
            )


async def setup(bot):
    await bot.add_cog(Connect4(bot))
