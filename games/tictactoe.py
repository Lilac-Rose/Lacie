import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio

class TicTacToeButton(discord.ui.Button):
    def __init__(self, x: int, y: int):
        super().__init__(style=discord.ButtonStyle.secondary, label='\u200b', row=y)
        self.x = x
        self.y = y

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeView = self.view

        if interaction.user.id != view.current_player.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        if view.board[self.y][self.x] != 0:
            await interaction.response.send_message("That spot is already taken!", ephemeral=True)
            return

        view.board[self.y][self.x] = view.current_mark
        self.label = view.current_symbol
        self.style = discord.ButtonStyle.primary if view.current_mark == 1 else discord.ButtonStyle.danger
        self.disabled = True

        winner = view.check_winner()
        if winner:
            for child in view.children:
                child.disabled = True
            view.stop()

            if winner == 3:
                await interaction.response.edit_message(content=f"It's a tie! 🤝", view=view)
            else:
                winner_user = view.player1 if winner == 1 else view.player2
                await interaction.response.edit_message(content=f"{winner_user.mention} wins! 🎉", view=view)
            return

        view.current_mark = 2 if view.current_mark == 1 else 1
        view.current_player = view.player2 if view.current_mark == 2 else view.player1
        view.current_symbol = "O" if view.current_mark == 2 else "X"

        await interaction.response.edit_message(
            content=f"{view.current_player.mention}'s turn ({view.current_symbol})",
            view=view
        )

class TicTacToeView(discord.ui.View):
    def __init__(self, player1: discord.Member, player2: discord.Member):
        super().__init__(timeout=300)  # 5 minute timeout
        self.player1 = player1
        self.player2 = player2

        self.current_mark = 1
        self.current_player = player1
        self.current_symbol = "X"

        # 0 = empty, 1 = player1 (X), 2 = player2 (O)
        self.board = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]

        for y in range(3):
            for x in range(3):
                self.add_item(TicTacToeButton(x, y))

    def check_winner(self):
        # Check rows
        for row in self.board:
            if row[0] == row[1] == row[2] != 0:
                return row[0]

        # Check columns
        for col in range(3):
            if self.board[0][col] == self.board[1][col] == self.board[2][col] != 0:
                return self.board[0][col]

        # Check diagonals
        if self.board[0][0] == self.board[1][1] == self.board[2][2] != 0:
            return self.board[0][0]
        if self.board[0][2] == self.board[1][1] == self.board[2][0] != 0:
            return self.board[0][2]

        # Check for tie
        if all(self.board[y][x] != 0 for y in range(3) for x in range(3)):
            return 3

        return None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        self.stop()

class ConfirmView(discord.ui.View):
    def __init__(self, player2: discord.Member):
        super().__init__(timeout=60)
        self.player2 = player2
        self.value = None

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player2.id:
            await interaction.response.send_message("Only the challenged player can accept!", ephemeral=True)
            return

        self.value = True
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player2.id:
            await interaction.response.send_message("Only the challenged player can decline!", ephemeral=True)
            return

        self.value = False
        self.stop()

class TicTacToe(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="tictactoe", description="Start a game of Tic-Tac-Toe with another user")
    @app_commands.describe(user="The user you want to play against")
    async def tictactoe(self, interaction: discord.Interaction, user: discord.Member):
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't play against yourself!", ephemeral=True)
            return

        if user.bot:
            await interaction.response.send_message("You can't play against a bot!", ephemeral=True)
            return

        confirm_view = ConfirmView(user)
        await interaction.response.send_message(
            f"{user.mention}, {interaction.user.mention} has challenged you to Tic-Tac-Toe! Do you accept?",
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

        game_view = TicTacToeView(interaction.user, user)

        if random.choice([True, False]):
            game_view.current_player = user
            game_view.current_mark = 2
            game_view.current_symbol = "O"

        await interaction.edit_original_response(
            content=f"Game started! {game_view.current_player.mention} goes first ({game_view.current_symbol})",
            view=game_view
        )

async def setup(bot):
    await bot.add_cog(TicTacToe(bot))
