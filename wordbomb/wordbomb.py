import discord
from discord.ext import commands
import random
import sqlite3
import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))

class WordBomb(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.db_path = os.path.join(self.base_dir, 'wordbomb.db')
        self.words_path = os.path.join(self.base_dir, 'words.txt')
        
        # Initialize database
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row
        self.c = self.db.cursor()
        self.initialize_database()
        
        # Load word list
        with open(self.words_path, 'r', encoding='utf-8') as f:
            self.words = [word.strip().lower() for word in f.readlines() if word.strip()]

    def initialize_database(self):
        """Initialize database schema"""
        self.c.executescript("""
        CREATE TABLE IF NOT EXISTS guilds (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            last_word TEXT NOT NULL DEFAULT '',
            last_substring TEXT NOT NULL DEFAULT ''
        );
        
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, guild_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (guild_id) REFERENCES guilds(id)
        );
        """)
        self.db.commit()

    async def get_word(self):
        """Generate word and substring with minimum 100 matches"""
        max_attempts = 1000
        attempts = 0
        
        while attempts < max_attempts:
            word = random.choice(self.words)
            word_length = len(word)
            substring_length = min(random.randint(3, 5), word_length)
            start = random.randint(0, word_length - substring_length)
            substring = word[start:start+substring_length]
            
            matching_words = await self.filter_words(substring)
            if len(matching_words) >= 100:
                return word, substring
            
            attempts += 1
        
        common_substrings = ['ing', 'ion', 'er', 'ed', 'es', 'tion', 'ter', 'ent', 'ant']
        for substring in common_substrings:
            matching_words = await self.filter_words(substring)
            if len(matching_words) >= 100:
                # Pick a random word containing this substring
                word = random.choice(matching_words)
                return word, substring
        
        # Ultimate fallback (should never reach here)
        return word, substring

    async def filter_words(self, substring):
        """Find all words containing the substring"""
        return [word for word in self.words if substring in word]

    async def check_answer(self, guild_id, answer):
        """Validate a player's answer"""
        answer = answer.strip().lower()
        self.c.execute("""
            SELECT last_substring, last_word 
            FROM guilds 
            WHERE id=?
        """, (guild_id,))
        result = self.c.fetchone()
        if not result:
            return False, None
        return result['last_substring'] in answer and answer in self.words, result['last_substring']

    async def update_score(self, user_id, guild_id):
        """Update score with proper error handling"""
        try:
            # Update user info
            self.c.execute("""
                INSERT INTO users (id, name)
                VALUES (?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name
            """, (user_id, str(user_id)))
            
            # Update score
            self.c.execute("""
                INSERT INTO scores (user_id, guild_id, score)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, guild_id) 
                DO UPDATE SET score = score + 1
            """, (user_id, guild_id))
            self.db.commit()
        except sqlite3.Error as e:
            print(f"Database error in update_score: {e}")
            self.db.rollback()
            raise
    
    async def get_user_score(self, user_id, guild_id):
        """Get current score for a user"""
        self.c.execute("""
            SELECT score FROM scores
            WHERE user_id=? AND guild_id=?
        """, (user_id, guild_id))
        result = self.c.fetchone()
        return result['score'] if result else 0

    async def check_for_game(self, guild_id, channel_id):
        """Check if a game exists in the channel"""
        self.c.execute("""
            SELECT 1 FROM guilds 
            WHERE id=? AND channel_id=?
        """, (guild_id, channel_id))
        return bool(self.c.fetchone())

    @commands.hybrid_command()
    async def start(self, ctx):
        """Start a Word Bomb game in this channel (Admin only)"""
        # Admin-role check
        if not any(role.id == ADMIN_ROLE_ID for role in ctx.author.roles):
            await ctx.send("❌ You do not have permission to start the game.", ephemeral=True)
            return

        if await self.check_for_game(ctx.guild.id, ctx.channel.id):
            await ctx.send("🚨 A game is already running in this channel!")
            return

        word, substring = await self.get_word()
        try:
            self.c.execute("""
                INSERT INTO guilds (id, name, channel_id, last_word, last_substring)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    channel_id=excluded.channel_id,
                    last_word=excluded.last_word,
                    last_substring=excluded.last_substring
            """, (ctx.guild.id, ctx.guild.name, ctx.channel.id, word, substring))
            self.db.commit()

            await ctx.send(
                f"# 💣 WORD BOMB STARTED\n"
                f"Find words containing:\n"
                f"{substring.upper()}"
            )

        except sqlite3.Error as e:
            await ctx.send("🚨 Failed to start game - database error")
            print(f"Database error in start: {e}")


    @commands.hybrid_command()
    async def end(self, ctx):
        """End the current Word Bomb game (Admin only)"""
        if not any(role.id == ADMIN_ROLE_ID for role in ctx.author.roles):
            await ctx.send("❌ You do not have permission to end the game.", ephemeral=True)
            return

        self.c.execute("DELETE FROM guilds WHERE id=?", (ctx.guild.id,))
        self.db.commit()
        await ctx.send("✅ Game ended!")

    @commands.hybrid_command()
    async def wordbomb_leaderboard(self, ctx):
        """Show top 10 players in this server"""
        self.c.execute("""
            SELECT user_id, score 
            FROM scores 
            WHERE guild_id=? 
            ORDER BY score DESC 
            LIMIT 10
        """, (ctx.guild.id,))
        top_players = self.c.fetchall()
        
        embed = discord.Embed(
            title="🏆 LEADERBOARD",
            color=discord.Color.gold()
        )
        
        if not top_players:
            embed.description = "No scores yet!"
        else:
            leaderboard_text = []
            for i, player in enumerate(top_players, 1):
                user = await self.client.fetch_user(player['user_id'])
                leaderboard_text.append(f"{i}. {user.mention} - {player['score']} points")
            
            embed.description = "\n".join(leaderboard_text)
            
        await ctx.send(embed=embed)

    @commands.hybrid_command()
    async def score(self, ctx, user: Optional[discord.User] = None):
        """Check your or another user's score"""
        target = user or ctx.author
        score = await self.get_user_score(target.id, ctx.guild.id)
        await ctx.send(f"⭐ {target.mention}'s score: **{score}**", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        if (message.author.bot or 
            not message.guild or 
            not await self.check_for_game(message.guild.id, message.channel.id)):
            return

        try:
            valid, last_substring = await self.check_answer(message.guild.id, message.content)
            if not valid:
                return

            new_word, new_substring = await self.get_word()
            num_words = len(await self.filter_words(new_substring))
            await self.update_score(message.author.id, message.guild.id)
            current_score = await self.get_user_score(message.author.id, message.guild.id)

            self.c.execute("""
                UPDATE guilds 
                SET last_word=?, last_substring=? 
                WHERE id=? AND channel_id=?
            """, (new_word, new_substring, message.guild.id, message.channel.id))
            self.db.commit()

            response = (
                f"# 🎯・NEW SUBSTRING ・🎯\n"
                f"# **{new_substring.upper()}**\n"
                f"## 🔠 Word Guessed\n"
                f"## {message.content.upper()}\n"
                f"## 📊 Stats\n"
                f"• Possible words: `{num_words:,}`\n"
            )

            await message.channel.send(response)

        except sqlite3.Error as e:
            print(f"Database error in on_message: {e}")
            await message.channel.send("⚠️ Database error - please try again")
            self.db.rollback()
        except Exception as e:
            print(f"Unexpected error in on_message: {e}")
            await message.channel.send("⚠️ An error occurred")

async def setup(client):
    await client.add_cog(WordBomb(client))