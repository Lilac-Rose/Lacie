import discord
from discord.ext import commands
from .loader import ModerationBase


class ModHelp(ModerationBase):
    @commands.command(name="modhelp")
    @ModerationBase.is_admin()
    async def modhelp(self, ctx):
        embeds = []

        def embed(title, color=discord.Color.blurple()):
            e = discord.Embed(title=title, color=color)
            return e

        e1 = embed("Moderation Commands — Member Actions", discord.Color.red())
        e1.add_field(name="!ban <user> [reason]", value="Ban a user. Accepts mention, ID, or name. Works even if they're not in the server. Sends a DM.", inline=False)
        e1.add_field(name="!cleanban <user> [days] [reason]", value="Ban a user and delete their recent messages. `days` is 1–7 (default 1). Sends a DM.", inline=False)
        e1.add_field(name="!kick <user> [reason]", value="Kick a user from the server. Sends a DM.", inline=False)
        e1.add_field(name="!unban <user> [reason]", value="Unban a user. Accepts mention, ID, or username.", inline=False)
        e1.add_field(name="!warn <user> [reason]", value="Issue a warning to a user. Sends a DM and logs the infraction.", inline=False)
        e1.add_field(name="!mute <user> <duration> [reason]", value="Mute a user for a set duration. Format: `1w`, `5d`, `12h`, `30m`. Auto-unmutes when time is up.", inline=False)
        e1.add_field(name="!unmute <user>", value="Manually remove a mute from a user.", inline=False)
        embeds.append(e1)

        e2 = embed("Moderation Commands — Purge", discord.Color.orange())
        e2.add_field(name="!purge <message_id>", value="Delete all messages up to (and including) the specified message ID in the current channel.", inline=False)
        e2.add_field(name="!purgemember <user> <message_id>", value="Delete messages from a specific user up to the specified message ID. Aliases: `purgeuser`, `purgeu`, `purgem`", inline=False)
        e2.add_field(name="!purgebot <message_id>", value="Delete bot messages up to the specified message ID. Aliases: `purgebots`, `purgeb`", inline=False)
        e2.add_field(name="!purgecontains <message_id> <text>", value="Delete messages containing specific text up to the specified message ID. Aliases: `purgec`, `purgetext`", inline=False)
        e2.add_field(name="!purgeembeds <message_id>", value="Delete messages that contain embeds up to the specified message ID. Aliases: `purgee`, `purgeembed`", inline=False)
        e2.add_field(name="!purgememberall <user_id>", value="Delete **all** messages from a user across every text channel. Requires confirmation. Aliases: `purgeuserall`, `purgeua`, `purgeallm`", inline=False)
        embeds.append(e2)

        e3 = embed("Moderation Commands — Channel & Infractions", discord.Color.gold())
        e3.add_field(name="!lock [channel]", value="Lock a channel so only staff can send messages. Defaults to the current channel. Saves original permissions for restore.", inline=False)
        e3.add_field(name="!unlock [channel]", value="Unlock a previously locked channel and restore its original permissions. Defaults to the current channel.", inline=False)
        e3.add_field(name="!checkperms [channel]", value="Check the bot's permissions in a channel and display role hierarchy info. Defaults to the current channel.", inline=False)
        e3.add_field(name="\u200b", value="**Infractions**", inline=False)
        e3.add_field(name="!inf search <user_id>", value="Show all active infractions for a user in this server.", inline=False)
        e3.add_field(name="!inf search_full <user_id>", value="Show the full infraction history for a user, including removed infractions.", inline=False)
        e3.add_field(name="!inf list", value="List all active infractions in this server.", inline=False)
        e3.add_field(name="!inf delete <id>", value="Permanently delete an infraction by its ID. The user is notified via DM.", inline=False)
        embeds.append(e3)

        e4 = embed("Moderation Commands — Logging", discord.Color.blue())
        e4.add_field(name="!log set <#channel> <type>", value="Route a log type to a channel. Use `!log types` to see all available types.", inline=False)
        e4.add_field(name="!log remove <type>", value="Remove the channel assignment for a log type.", inline=False)
        e4.add_field(name="!log list", value="Show all configured log types and their channels.", inline=False)
        e4.add_field(name="!log types", value="List every available log type.", inline=False)
        e4.add_field(name="!log exclude <channel_id>", value="Exclude a channel from being logged. Events in that channel won't appear in any log.", inline=False)
        e4.add_field(name="!log unexclude <channel_id>", value="Remove a channel from the exclusion list.", inline=False)
        e4.add_field(name="!log excluded", value="List all channels currently excluded from logging.", inline=False)
        e4.add_field(name="!log clear", value="Remove **all** logging configurations for this server. Requires confirmation.", inline=False)
        embeds.append(e4)

        e5 = embed("Moderation Commands — Tools", discord.Color.green())
        e5.add_field(name="!send_embed <#channel> <embed_string>", value="Send an embed (built with the embed builder) to a channel. Previews before sending. Requires confirmation.", inline=False)
        e5.set_footer(text="Arguments in <> are required. Arguments in [] are optional.")
        embeds.append(e5)

        await ctx.send(embeds=embeds)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModHelp(bot))
