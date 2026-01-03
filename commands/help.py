import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import difflib

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    def get_command_signature(self, command):
        """Get the usage signature for a command"""
        if isinstance(command, commands.HybridCommand):
            # For hybrid commands, show both formats
            params = []
            for name, param in command.clean_params.items():
                if param.default == param.empty:
                    params.append(f"<{name}>")
                else:
                    params.append(f"[{name}]")
            param_str = " ".join(params)
            return f"!{command.name} {param_str}\n/{command.name} {param_str}"
        else:
            return f"{command.qualified_name} {command.signature}"
    
    def get_all_commands(self):
        """Get all commands organized by cog"""
        cog_commands = {}
        
        for cog_name, cog in self.bot.cogs.items():
            commands_list = []
            
            # Get regular commands
            for cmd in cog.get_commands():
                if not cmd.hidden:
                    commands_list.append(cmd)
            
            # Get app commands (slash only)
            if hasattr(cog, '__cog_app_commands__'):
                for cmd in cog.__cog_app_commands__:
                    if isinstance(cmd, app_commands.Command):
                        commands_list.append(cmd)
                    elif isinstance(cmd, app_commands.Group):
                        # Add group commands
                        commands_list.append(cmd)
            
            if commands_list:
                cog_commands[cog_name] = commands_list
        
        # Get commands not in cogs
        no_cog_commands = [cmd for cmd in self.bot.commands if not cmd.cog and not cmd.hidden]
        if no_cog_commands:
            cog_commands["Other"] = no_cog_commands
        
        return cog_commands
    
    def search_commands(self, query):
        """Search for commands matching the query"""
        query = query.lower()
        results = []
        
        for cog_name, cog in self.bot.cogs.items():
            for cmd in cog.get_commands():
                if not cmd.hidden:
                    # Check command name
                    if query in cmd.name.lower():
                        results.append((cmd, cog_name, 100))
                    # Check command aliases
                    elif any(query in alias.lower() for alias in cmd.aliases):
                        results.append((cmd, cog_name, 90))
                    # Check description
                    elif cmd.description and query in cmd.description.lower():
                        results.append((cmd, cog_name, 70))
                    # Check help text
                    elif cmd.help and query in cmd.help.lower():
                        results.append((cmd, cog_name, 60))
        
        # Sort by relevance
        results.sort(key=lambda x: x[2], reverse=True)
        return results
    
    def create_help_embed(self, title, description=None):
        """Create a base help embed"""
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Use !help <command> or /help <command> for more info on a specific command")
        return embed
    
    @commands.hybrid_command(name="help", description="Shows help information for commands")
    @app_commands.describe(command="The command to get help for")
    async def help_command(self, ctx: commands.Context, *, command: Optional[str] = None):
        """
        Get help for bot commands
        
        Usage:
          !help - Show all commands
          !help <command> - Get detailed help for a specific command
          !help <search> - Search for commands
        """
        
        if command:
            # Try to find exact command match first
            cmd = self.bot.get_command(command.lower())
            
            if cmd:
                # Show detailed help for specific command
                embed = self.create_help_embed(
                    title=f"Help: {cmd.name}",
                    description=cmd.help or cmd.description or "No description available"
                )
                
                # Usage
                embed.add_field(
                    name="Usage",
                    value=f"```\n{self.get_command_signature(cmd)}\n```",
                    inline=False
                )
                
                # Aliases
                if cmd.aliases:
                    embed.add_field(
                        name="Aliases",
                        value=", ".join(f"`{alias}`" for alias in cmd.aliases),
                        inline=False
                    )
                
                # Category
                if cmd.cog:
                    embed.add_field(name="Category", value=cmd.cog.qualified_name, inline=True)
                
                await ctx.send(embed=embed)
            else:
                # Search for commands
                results = self.search_commands(command)
                
                if not results:
                    # Suggest similar commands
                    all_cmd_names = [c.name for c in self.bot.commands]
                    suggestions = difflib.get_close_matches(command.lower(), all_cmd_names, n=3, cutoff=0.6)
                    
                    embed = discord.Embed(
                        title="❌ Command Not Found",
                        description=f"No command found matching `{command}`",
                        color=discord.Color.red()
                    )
                    
                    if suggestions:
                        embed.add_field(
                            name="Did you mean?",
                            value="\n".join(f"• `{s}`" for s in suggestions),
                            inline=False
                        )
                    
                    await ctx.send(embed=embed)
                else:
                    # Show search results
                    embed = self.create_help_embed(
                        title=f"🔍 Search Results for '{command}'",
                        description=f"Found {len(results)} matching command(s)"
                    )
                    
                    for cmd, cog_name, score in results[:10]:  # Limit to 10 results
                        desc = cmd.description or cmd.help or "No description"
                        if len(desc) > 100:
                            desc = desc[:97] + "..."
                        
                        embed.add_field(
                            name=f"{cmd.name} ({cog_name})",
                            value=desc,
                            inline=False
                        )
                    
                    if len(results) > 10:
                        embed.set_footer(text=f"Showing top 10 of {len(results)} results. Use !help <command> for details.")
                    
                    await ctx.send(embed=embed)
        else:
            # Show all commands organized by category
            cog_commands = self.get_all_commands()
            
            embed = self.create_help_embed(
                title="📚 Bot Commands",
                description=f"Prefix: `!` | Total Commands: {len(list(self.bot.commands))}\n\n"
                           "Commands work with both `!` and `/`"
            )
            
            for cog_name, cmds in sorted(cog_commands.items()):
                if not cmds:
                    continue
                
                # Group commands by name
                cmd_names = []
                seen = set()
                
                for cmd in cmds:
                    if isinstance(cmd, (commands.Command, commands.HybridCommand)):
                        name = cmd.name
                    elif isinstance(cmd, (app_commands.Command, app_commands.Group)):
                        name = cmd.name
                    else:
                        continue
                    
                    if name not in seen:
                        cmd_names.append(f"`{name}`")
                        seen.add(name)
                
                if cmd_names:
                    embed.add_field(
                        name=f"**{cog_name}**",
                        value=" • ".join(cmd_names),
                        inline=False
                    )
            
            await ctx.send(embed=embed)
    
    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error):
        """Show help if command not found"""
        if isinstance(error, commands.CommandNotFound):
            # Extract the attempted command
            cmd_used = ctx.message.content.split()[0][len(ctx.prefix):]
            
            # Suggest similar commands
            all_cmd_names = [c.name for c in self.bot.commands]
            suggestions = difflib.get_close_matches(cmd_used, all_cmd_names, n=3, cutoff=0.6)
            
            embed = discord.Embed(
                title="❓ Unknown Command",
                description=f"Command `{cmd_used}` not found.",
                color=discord.Color.orange()
            )
            
            if suggestions:
                embed.add_field(
                    name="Did you mean?",
                    value="\n".join(f"• `!{s}` or `/{s}`" for s in suggestions),
                    inline=False
                )
            
            embed.set_footer(text="Use !help to see all commands")
            await ctx.send(embed=embed, delete_after=10)

async def setup(bot):
    # Remove default help command
    bot.remove_command('help')
    await bot.add_cog(Help(bot))