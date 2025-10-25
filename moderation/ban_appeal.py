import discord
from discord.ext import commands
import asyncio
import traceback

APPEAL_GUILD_ID = 876772600704020530
APPEAL_CATEGORY_ID = 1220467221130776647
APPEAL_LOG_CHANNEL_ID = 1431693393922359336


class BanAppeal(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_appeals = {}  # user_id: {'channel_id': int, 'task': Task}
        self.bot.loop.create_task(self.restore_appeals())

    def cog_unload(self):
        """Cancel all active relay tasks when cog is unloaded."""
        self.log("Cog unloading - cancelling all active relay tasks")
        for user_id, appeal_data in self.active_appeals.items():
            if 'task' in appeal_data and not appeal_data['task'].done():
                appeal_data['task'].cancel()
                self.log(f"Cancelled relay task for user {user_id}")
        self.active_appeals.clear()

    def log(self, message: str):
        """Simple logging helper that prints to stdout (PM2 captures this)."""
        print(f"[BanAppeal] {message}", flush=True)

    async def restore_appeals(self):
        """Restore active appeal relays after bot restart."""
        await self.bot.wait_until_ready()
        
        guild = self.bot.get_guild(APPEAL_GUILD_ID)
        if not guild:
            return
        
        category = guild.get_channel(APPEAL_CATEGORY_ID)
        if not category:
            return
        
        for channel in category.text_channels:
            if channel.topic and "Ban appeal for" in channel.topic:
                try:
                    user_id = int(channel.topic.split("(")[-1].split(")")[0])
                    if user_id in self.active_appeals:
                        self.log(f"⏭️ Skipping {channel.name} - already has active relay")
                        continue
                    
                    user = await self.bot.fetch_user(user_id)
                    task = self.bot.loop.create_task(self.appeal_relay(user, channel))
                    self.active_appeals[user_id] = {'channel_id': channel.id, 'task': task}
                    self.log(f"✅ Restored appeal relay for {user} ({user_id})")
                except Exception as e:
                    self.log(f"⚠️ Could not restore appeal for channel {channel.name}: {e}")

    @commands.command(name="appeal")
    async def appeal(self, ctx):
        """Start a ban appeal process."""
        if ctx.guild:
            await ctx.send("This command can only be used in DMs with me.")
            return

        user = ctx.author
        self.log(f"Appeal started by {user} ({user.id})")

        try:
            guild = self.bot.get_guild(APPEAL_GUILD_ID)
            if not guild:
                self.log(f"Error: Guild with ID {APPEAL_GUILD_ID} not found.")
                await ctx.send("Server not found, please contact the moderators manually.")
                return

            if user.id in self.active_appeals:
                await ctx.send("You already have an active ban appeal. Please wait for staff to respond.")
                return

            await ctx.send("Please explain why you think your ban was unfair:")
            msg = await self.bot.wait_for(
                "message",
                timeout=300,
                check=lambda m: m.author == user and isinstance(m.channel, discord.DMChannel)
            )
            reason = msg.content.strip()
            self.log(f"Received appeal reason from {user}: {reason}")

            category = guild.get_channel(APPEAL_CATEGORY_ID)
            if not category:
                self.log(f"Error: Category ID {APPEAL_CATEGORY_ID} not found in guild {guild.id}.")
                await ctx.send("Category not found in server. Please contact moderators directly.")
                return

            channel_name = f"{user.name}-ban-appeal"
            self.log(f"Creating appeal channel '{channel_name}' in category '{category.name}'...")
            try:
                channel = await guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    topic=f"Ban appeal for {user} ({user.id})"
                )
            except discord.Forbidden:
                self.log(f"❌ Forbidden: Bot missing 'Manage Channels' permission in {guild.name}.")
                await ctx.send("I don't have permission to create channels in that server.")
                return
            except Exception as e:
                self.log(f"❌ Exception during channel creation: {e}")
                traceback.print_exc()
                await ctx.send("An error occurred while creating your appeal channel.")
                return

            self.log(f"✅ Created channel '{channel.name}' ({channel.id}) for {user}.")

            log_channel = guild.get_channel(APPEAL_LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(f"📨 New ban appeal created by **{user}** (<@{user.id}>) in {channel.mention}")
            else:
                self.log(f"⚠️ Could not find log channel with ID {APPEAL_LOG_CHANNEL_ID}.")

            await channel.send(
                f"**New Ban Appeal**\nUser: {user.mention} ({user.id})\nReason:\n```{reason}```\n"
                f"Staff can reply here, and messages will be sent to the user.\n"
                f"Use `!close` to close this appeal."
            )

            await ctx.send(
                "✅ Your appeal has been created. Staff will review your case soon. "
                "You can continue sending messages here if you'd like."
            )

            task = self.bot.loop.create_task(self.appeal_relay(user, channel))
            self.active_appeals[user.id] = {'channel_id': channel.id, 'task': task}

        except asyncio.TimeoutError:
            await ctx.send("You took too long to respond. Please start again with `!appeal`.")
            self.log(f"Appeal timeout for {user} ({user.id})")
        except Exception as e:
            self.log(f"Unexpected error during appeal setup: {e}")
            traceback.print_exc()
            await ctx.send("An unexpected error occurred. Please contact staff.")

    async def appeal_relay(self, user, staff_channel):
        """Relays messages between the user and staff."""
        self.log(f"Starting message relay for {user} ({user.id}) <-> #{staff_channel.name}")

        def user_check(m):
            return m.author == user and isinstance(m.channel, discord.DMChannel)

        def staff_check(m):
            return m.channel.id == staff_channel.id and not m.author.bot

        try:
            while True:
                user_task = asyncio.create_task(self.bot.wait_for("message", check=user_check))
                staff_task = asyncio.create_task(self.bot.wait_for("message", check=staff_check))
                
                done, pending = await asyncio.wait(
                    [user_task, staff_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                for task in pending:
                    task.cancel()

                msg = done.pop().result()

                # User → Staff
                if isinstance(msg.channel, discord.DMChannel):
                    self.log(f"User → Staff: {user}: {msg.content}")
                    try:
                        embed = discord.Embed(description=msg.content or "*[No text content]*", color=discord.Color.blurple())
                        embed.set_author(name=f"{user}", icon_url=user.display_avatar.url)
                        
                        if msg.attachments:
                            self.log(f"Processing {len(msg.attachments)} attachment(s)")
                            for att in msg.attachments:
                                self.log(f"  - {att.filename}, type: {att.content_type}, url: {att.url}")
                            first_att = msg.attachments[0]
                            if first_att.content_type and 'image' in first_att.content_type.lower():
                                embed.set_image(url=first_att.url)
                            attachment_list = "\n".join([f"[{att.filename}]({att.url})" for att in msg.attachments])
                            embed.add_field(name="Attachments", value=attachment_list, inline=False)
                        
                        await staff_channel.send(embed=embed)
                    except Exception as e:
                        self.log(f"⚠️ Failed to send message to staff channel: {e}")
                        traceback.print_exc()

                # Staff → User
                elif msg.channel == staff_channel:
                    if msg.content.startswith("="):
                        self.log(f"Staff internal note in {staff_channel.name}: {msg.content}")
                        continue
                    
                    self.log(f"Staff → User: {msg.author} → {user}")
                    try:
                        embed = discord.Embed(description=msg.content or "*[No text content]*", color=discord.Color.green())
                        embed.set_author(name=f"Staff - {msg.author.name}", icon_url=msg.author.display_avatar.url)
                        
                        if msg.attachments:
                            self.log(f"Processing {len(msg.attachments)} attachment(s) from staff")
                            for att in msg.attachments:
                                self.log(f"  - {att.filename}, type: {att.content_type}, url: {att.url}")
                            first_att = msg.attachments[0]
                            if first_att.content_type and 'image' in first_att.content_type.lower():
                                embed.set_image(url=first_att.url)
                            attachment_list = "\n".join([f"[{att.filename}]({att.url})" for att in msg.attachments])
                            embed.add_field(name="Attachments", value=attachment_list, inline=False)
                        
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        self.log(f"⚠️ Cannot send DM to user {user} - DMs disabled")
                        await staff_channel.send("⚠️ Could not send message to user (DMs are disabled).")
                    except Exception as e:
                        self.log(f"⚠️ Failed to send message to user {user}: {e}")
                        await staff_channel.send(f"⚠️ Could not send message to user: {e}")

        except asyncio.CancelledError:
            self.log(f"Relay task cancelled for {user} ({user.id})")
            raise
        except Exception as e:
            self.log(f"❌ Error in appeal relay for {user}: {e}")
            traceback.print_exc()
            try:
                await staff_channel.send(f"⚠️ **Relay Error:** The message relay has stopped due to an error. Please manually notify the user or restart the appeal.")
            except:
                pass

    @commands.command(name="close")
    async def close(self, ctx):
        """Close a ban appeal ticket."""
        if not ctx.channel.category or ctx.channel.category.id != APPEAL_CATEGORY_ID:
            return

        self.log(f"Closing appeal channel: {ctx.channel.name} by {ctx.author}")

        guild = ctx.guild
        log_channel = guild.get_channel(APPEAL_LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🛑 Ban appeal for **{ctx.channel.name}** has been closed by {ctx.author.mention}.")
        else:
            self.log("⚠️ Could not find appeal log channel for close event.")

        user_to_notify = None
        for uid, appeal_data in list(self.active_appeals.items()):
            if appeal_data['channel_id'] == ctx.channel.id:
                try:
                    user_to_notify = await self.bot.fetch_user(uid)
                except Exception as e:
                    self.log(f"⚠️ Could not fetch user {uid} to notify: {e}")
                if 'task' in appeal_data and not appeal_data['task'].done():
                    appeal_data['task'].cancel()
                del self.active_appeals[uid]
                self.log(f"Removed appeal tracking for user {uid}")
                break

        if user_to_notify:
            try:
                embed = discord.Embed(
                    title="Appeal Closed",
                    description=f"Your ban appeal has been closed by staff member **{ctx.author.name}**.",
                    color=discord.Color.red()
                )
                await user_to_notify.send(embed=embed)
                self.log(f"✅ Notified {user_to_notify} that their appeal was closed")
            except Exception as e:
                self.log(f"⚠️ Could not notify user {user_to_notify}: {e}")

        await ctx.send("Closing appeal channel in 5 seconds...")
        await asyncio.sleep(5)

        try:
            await ctx.channel.delete(reason="Ban appeal closed")
            self.log(f"✅ Appeal channel '{ctx.channel.name}' deleted.")
        except Exception as e:
            self.log(f"❌ Failed to delete channel: {e}")
            traceback.print_exc()


async def setup(bot):
    await bot.add_cog(BanAppeal(bot))
