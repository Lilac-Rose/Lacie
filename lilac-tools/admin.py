"""Owner-only admin tools: database browser, terminal, eval, file manager."""
import discord
from discord.ext import commands
import aiosqlite
import asyncio
import os
import glob
from typing import Optional
import re
from utils.logger import get_logger

logger = get_logger(__name__)

ADMIN_USER_ID = 252130669919076352

# Security configuration
BLOCKED_PATHS = [
    '.env',
    '.env.local',
    '.env.production',
    'config.json',
    'secrets.json',
    'credentials.json',
    '.git',
    'id_rsa',
    'id_ed25519',
    '.pem',
    '.key',
    'private_key',
    'secret_key',
]

BLOCKED_PATTERNS = [
    r'.*\.env.*',
    r'.*secret.*',
    r'.*password.*',
    r'.*token.*',
    r'.*api[_-]?key.*',
    r'.*private[_-]?key.*',
    r'.*\.pem$',
    r'.*\.key$',
    r'.*/\.ssh/.*',
    r'.*/\.aws/.*',
]

BLOCKED_COMMANDS = [
    'rm -rf',
    'dd if=',
    'mkfs',
    'fdisk',
    ':(){ :|:& };:',  # Fork bomb
    'chmod 777',
    'chmod -R 777',
]

def is_owner():
    """Check if the user is the bot owner"""
    async def predicate(ctx):
        return ctx.author.id == ADMIN_USER_ID
    return commands.check(predicate)

def is_path_safe(path):
    """Check if a path is safe to access"""
    # Normalize the path
    normalized = os.path.normpath(path)
    
    # Check against blocked paths
    for blocked in BLOCKED_PATHS:
        if blocked.lower() in normalized.lower():
            return False
    
    # Check against blocked patterns
    for pattern in BLOCKED_PATTERNS:
        if re.match(pattern, normalized.lower()):
            return False
    
    return True

def is_command_safe(command):
    """Check if a command is safe to execute"""
    command_lower = command.lower()
    for blocked in BLOCKED_COMMANDS:
        if blocked.lower() in command_lower:
            return False
    return True

class AdminCommands(commands.Cog):
    """Admin-only commands for database queries and terminal access"""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_connections = {}
        asyncio.create_task(self._discover_databases())
    
    async def _discover_databases(self):
        """Discover all .db files in the project"""
        loop = asyncio.get_event_loop()
        
        def _glob():
            all_dbs = glob.glob("**/*.db", recursive=True)
            # Filter out backup directories
            return [f for f in all_dbs if not any(x in f for x in ['backups/', 'old_backups/'])]
        
        db_files = await loop.run_in_executor(None, _glob)
        self.db_connections = {os.path.basename(f).replace('.db', ''): f for f in db_files}
        logger.info(f"Discovered databases: {list(self.db_connections.keys())}")
    
    @commands.command(name="admin_help", aliases=["adminhelp", "ahelp"])
    @is_owner()
    async def admin_help(self, ctx, category: Optional[str] = None):
        """Show all admin commands. Usage: !admin_help [category]
        Categories: code, db, terminal, files, dev"""
        
        if category and category.lower() == "code":
            embed = discord.Embed(
                title="📝 Code Management Commands",
                description="Commands for viewing and editing code files",
                color=discord.Color.blue()
            )
            
            commands_list = [
                ("!code view `<file>`", "View file with syntax highlighting and line numbers"),
                ("!code search `<pattern>` `[path]`", "Search for code patterns across files (regex supported)"),
                ("!code find `<file>` `<text>`", "Find specific text in a file and show line numbers"),
                ("!code edit `<file>` `<line>` `[end]`", "Edit line(s) with interactive popup editor"),
                ("!code insert `<file>` `<line>` `<text>`", "Insert new line at position"),
                ("!code delete `<file>` `<line>`", "Delete specific line"),
                ("!code replace `<file>` `\"find\"` `\"replace\"` `[--all]`", "Find and replace text"),
                ("!code backup `<file>`", "Create timestamped backup"),
                ("!code diff `<file1>` `<file2>`", "Compare two files"),
            ]
            
            for cmd, desc in commands_list:
                embed.add_field(name=cmd, value=desc, inline=False)
            
            embed.set_footer(text="Example: !code edit bot.py 42")
            await ctx.send(embed=embed)
            return
        
        elif category and category.lower() == "db":
            embed = discord.Embed(
                title="🗄️ Database Commands",
                description="Commands for querying and managing SQLite databases",
                color=discord.Color.green()
            )
            
            commands_list = [
                ("!dblist", "List all discovered .db files"),
                ("!dbtables `[db_name]`", "List all tables in a database"),
                ("!dbinfo `<db>` `<table>`", "Show table schema and column info"),
                ("!dbquery `<db>` `<sql>`", "Execute SELECT query (read-only)"),
                ("!dbexec `<db>` `<sql>`", "Execute UPDATE/DELETE/INSERT (write operations)"),
            ]
            
            for cmd, desc in commands_list:
                embed.add_field(name=cmd, value=desc, inline=False)
            
            embed.set_footer(text="Example: !dbquery mydb SELECT * FROM users LIMIT 10")
            await ctx.send(embed=embed)
            return
        
        elif category and category.lower() == "terminal":
            embed = discord.Embed(
                title="🖥️ Terminal Commands",
                description="Commands for executing shell commands",
                color=discord.Color.red()
            )
            
            commands_list = [
                ("!terminal `<command>`", "Execute shell command (30s timeout, blocks dangerous commands)"),
                ("!term `<command>`", "Alias for !terminal"),
                ("!sh `<command>`", "Alias for !terminal"),
            ]
            
            for cmd, desc in commands_list:
                embed.add_field(name=cmd, value=desc, inline=False)
            
            embed.add_field(name="⚠️ Blocked Commands", value="rm -rf, dd, mkfs, fdisk, fork bombs, chmod 777", inline=False)
            embed.set_footer(text="Example: !terminal git status")
            await ctx.send(embed=embed)
            return
        
        elif category and category.lower() == "files":
            embed = discord.Embed(
                title="📁 File System Commands",
                description="Commands for navigating and viewing files",
                color=discord.Color.purple()
            )
            
            commands_list = [
                ("!pwd", "Show current working directory"),
                ("!ls `[path]`", "List files and directories"),
            ]
            
            for cmd, desc in commands_list:
                embed.add_field(name=cmd, value=desc, inline=False)
            
            embed.set_footer(text="Example: !ls cogs/")
            await ctx.send(embed=embed)
            return
        
        elif category and category.lower() == "dev":
            embed = discord.Embed(
                title="🔧 Development Commands",
                description="Commands for testing and debugging",
                color=discord.Color.orange()
            )
            
            commands_list = [
                ("!eval `<code>`", "Evaluate Python code with bot context"),
            ]
            
            for cmd, desc in commands_list:
                embed.add_field(name=cmd, value=desc, inline=False)
            
            embed.add_field(name="Available in eval context", value="`bot`, `ctx`, `discord`, `commands`, `asyncio`, `os`, `aiosqlite`", inline=False)
            embed.set_footer(text="Example: !eval await ctx.send('Hello!')")
            await ctx.send(embed=embed)
            return
        
        # Main help menu
        embed = discord.Embed(
            title="🛡️ Admin Commands Help",
            description="All commands available to the bot owner",
            color=discord.Color.gold()
        )
        
        categories = [
            ("📝 Code Management", "`!admin_help code`", "View, edit, search, and manage code files"),
            ("🗄️ Database", "`!admin_help db`", "Query and manage SQLite databases"),
            ("🖥️ Terminal", "`!admin_help terminal`", "Execute shell commands"),
            ("📁 File System", "`!admin_help files`", "Navigate and view files"),
            ("🔧 Development", "`!admin_help dev`", "Testing and debugging tools"),
        ]
        
        for title, command, description in categories:
            embed.add_field(name=f"{title}", value=f"{description}\nUse {command} for details", inline=False)
        
        embed.add_field(
            name="🔒 Security Features",
            value="• Blocks access to .env, secrets, keys\n• Prevents dangerous commands\n• File size limits (1MB)\n• Command timeouts (30s)",
            inline=False
        )
        
        embed.set_footer(text=f"Bot Owner: {ADMIN_USER_ID} • All commands require owner permissions")
        await ctx.send(embed=embed)

    
    async def _format_results(self, results, description):
        """Format SQL results into a readable string"""
        if not results:
            return "No results found."
        
        loop = asyncio.get_event_loop()
        
        def _format():
            # Get column names
            cols = [desc[0] for desc in description]
            
            # Calculate column widths
            widths = [len(col) for col in cols]
            for row in results:
                for i, val in enumerate(row):
                    widths[i] = max(widths[i], len(str(val)))
            
            # Build table
            lines = []
            header = " | ".join(col.ljust(widths[i]) for i, col in enumerate(cols))
            lines.append(header)
            lines.append("-" * len(header))
            
            for row in results:
                line = " | ".join(str(val).ljust(widths[i]) for i, val in enumerate(row))
                lines.append(line)
            
            return "\n".join(lines)
        
        return await loop.run_in_executor(None, _format)
    
    @commands.command(name="dblist")
    @is_owner()
    async def db_list(self, ctx):
        """List all available databases"""
        await self._discover_databases()
        if not self.db_connections:
            await ctx.send("❌ No databases found!")
            return
        
        # Split databases into chunks to avoid embed size limit
        db_items = sorted(self.db_connections.items())
        chunk_size = 20  # 20 databases per page
        total_dbs = len(db_items)
        total_pages = (total_dbs + chunk_size - 1) // chunk_size  # Ceiling division
        
        if total_pages == 1:
            # Just send one embed if it fits
            db_list = "\n".join(f"• **{name}**: `{path}`" for name, path in db_items)
            embed = discord.Embed(
                title=f"📊 Available Databases ({total_dbs} total)",
                description=db_list,
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)
            return
        
        # Multi-page view
        current_page = 0
        
        def get_page_embed(page):
            start = page * chunk_size
            end = min(start + chunk_size, total_dbs)
            chunk = db_items[start:end]
            db_list = "\n".join(f"• **{name}**: `{path}`" for name, path in chunk)
            
            embed = discord.Embed(
                title=f"📊 Available Databases",
                description=db_list,
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Page {page + 1}/{total_pages} • {total_dbs} databases total")
            return embed
        
        # Create view with buttons
        view = discord.ui.View(timeout=180)
        
        async def update_message(interaction, new_page):
            nonlocal current_page
            current_page = new_page
            
            # Update button states
            first_button.disabled = (current_page == 0)
            prev_button.disabled = (current_page == 0)
            next_button.disabled = (current_page == total_pages - 1)
            last_button.disabled = (current_page == total_pages - 1)
            
            await interaction.response.edit_message(embed=get_page_embed(current_page), view=view)
        
        # Button callbacks
        async def first_callback(interaction):
            await update_message(interaction, 0)
        
        async def prev_callback(interaction):
            await update_message(interaction, max(0, current_page - 1))
        
        async def next_callback(interaction):
            await update_message(interaction, min(total_pages - 1, current_page + 1))
        
        async def last_callback(interaction):
            await update_message(interaction, total_pages - 1)
        
        # Create buttons
        first_button = discord.ui.Button(label="⏮️", style=discord.ButtonStyle.gray, disabled=True)
        first_button.callback = first_callback
        
        prev_button = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary, disabled=True)
        prev_button.callback = prev_callback
        
        next_button = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary)
        next_button.callback = next_callback
        
        last_button = discord.ui.Button(label="⏭️", style=discord.ButtonStyle.gray)
        last_button.callback = last_callback
        
        view.add_item(first_button)
        view.add_item(prev_button)
        view.add_item(next_button)
        view.add_item(last_button)
        
        await ctx.send(embed=get_page_embed(current_page), view=view)
    
    @commands.command(name="dbtables")
    @is_owner()
    async def db_tables(self, ctx, db_name: Optional[str] = None):
        """List all tables in a database. Usage: !dbtables [db_name]"""
        if db_name is None:
            if len(self.db_connections) == 1:
                db_name = list(self.db_connections.keys())[0]
            else:
                await ctx.send("❌ Please specify a database name. Use `!dblist` to see available databases.")
                return
        
        if db_name not in self.db_connections:
            await ctx.send(f"❌ Database '{db_name}' not found. Use `!dblist` to see available databases.")
            return
        
        try:
            async with aiosqlite.connect(self.db_connections[db_name]) as conn:
                async with conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;") as cur:
                    tables = await cur.fetchall()
            
            if not tables:
                await ctx.send(f"No tables found in database '{db_name}'")
                return
            
            table_list = "\n".join(f"• `{table[0]}`" for table in tables)
            embed = discord.Embed(
                title=f"📋 Tables in {db_name}",
                description=table_list,
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    @commands.command(name="dbinfo")
    @is_owner()
    async def db_info(self, ctx, db_name: str, table_name: str):
        """Get schema info for a table. Usage: !dbinfo <db_name> <table_name>"""
        if db_name not in self.db_connections:
            await ctx.send(f"❌ Database '{db_name}' not found. Use `!dblist` to see available databases.")
            return
        
        try:
            async with aiosqlite.connect(self.db_connections[db_name]) as conn:
                async with conn.execute(f"PRAGMA table_info({table_name});") as cur:
                    info = await cur.fetchall()
            
            if not info:
                await ctx.send(f"❌ Table '{table_name}' not found in database '{db_name}'")
                return
            
            # Format schema info
            schema = []
            for col in info:
                col_id, name, dtype, not_null, default, pk = col
                parts = [f"`{name}`", dtype]
                if pk:
                    parts.append("PRIMARY KEY")
                if not_null:
                    parts.append("NOT NULL")
                if default is not None:
                    parts.append(f"DEFAULT {default}")
                schema.append(" ".join(parts))
            
            embed = discord.Embed(
                title=f"🔍 Schema: {db_name}.{table_name}",
                description="\n".join(schema),
                color=discord.Color.purple()
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    @commands.command(name="dbquery")
    @is_owner()
    async def db_query(self, ctx, db_name: str, *, query: str):
        """Execute a SQL query. Usage: !dbquery <db_name> <sql_query>"""
        if db_name not in self.db_connections:
            await ctx.send(f"❌ Database '{db_name}' not found. Use `!dblist` to see available databases.")
            return
        
        # Safety check - prevent destructive operations by default
        query_upper = query.strip().upper()
        dangerous_keywords = ["DROP", "DELETE", "TRUNCATE", "ALTER"]
        if any(keyword in query_upper.split()[0:2] for keyword in dangerous_keywords):
            await ctx.send(f"⚠️ Destructive operation detected. Use `!dbexec` for DELETE/DROP/ALTER commands.")
            return
        
        try:
            async with aiosqlite.connect(self.db_connections[db_name]) as conn:
                async with conn.execute(query) as cur:
                    results = await cur.fetchall()
                    description = cur.description
            
            # Format results
            output = await self._format_results(results, description)
            
            # Handle long outputs
            if len(output) > 1900:
                # Save to file
                filename = f"query_results_{ctx.message.id}.txt"
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._write_file, filename, output)
                await ctx.send(f"📊 Results ({len(results)} rows):", file=discord.File(filename))
                await loop.run_in_executor(None, os.remove, filename)
            else:
                await ctx.send(f"```\n{output}\n```")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    def _write_file(self, filename, content):
        """Helper to write file synchronously in executor"""
        with open(filename, "w") as f:
            f.write(content)
    
    @commands.command(name="dbexec")
    @is_owner()
    async def db_exec(self, ctx, db_name: str, *, query: str):
        """Execute a SQL statement (including destructive ones). Usage: !dbexec <db_name> <sql_statement>"""
        if db_name not in self.db_connections:
            await ctx.send(f"❌ Database '{db_name}' not found. Use `!dblist` to see available databases.")
            return
        
        try:
            async with aiosqlite.connect(self.db_connections[db_name]) as conn:
                async with conn.execute(query) as cur:
                    affected_rows = cur.rowcount
                await conn.commit()
            
            await ctx.send(f"✅ Query executed successfully. Rows affected: {affected_rows}")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    @commands.command(name="terminal", aliases=["term", "sh"])
    @is_owner()
    async def terminal(self, ctx, *, command: str):
        """Execute a shell command. Usage: !terminal <command>"""
        # Security check
        if not is_command_safe(command):
            await ctx.send("❌ Command blocked for security reasons.")
            return
        
        try:
            # Execute command with timeout using async subprocess
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.getcwd()
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
            except asyncio.TimeoutError:
                process.kill()
                await ctx.send("❌ Command timed out (30 second limit)")
                return
            
            output = stdout.decode() if stdout else stderr.decode()
            if not output:
                output = "Command executed with no output."
            
            # Handle long outputs
            if len(output) > 1900:
                filename = f"terminal_output_{ctx.message.id}.txt"
                loop = asyncio.get_event_loop()
                content = f"Command: {command}\nExit code: {process.returncode}\n{'-' * 50}\n{output}"
                await loop.run_in_executor(None, self._write_file, filename, content)
                await ctx.send(f"🖥️ Output (exit code: {process.returncode}):", file=discord.File(filename))
                await loop.run_in_executor(None, os.remove, filename)
            else:
                await ctx.send(f"```\n{output}\n```\nExit code: {process.returncode}")
        
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    @commands.command(name="eval")
    @is_owner()
    async def eval_code(self, ctx, *, code: str):
        """Evaluate Python code. Usage: !eval <code>"""
        # Clean up code block formatting if present
        if code.startswith("```python") and code.endswith("```"):
            code = code[9:-3].strip()
        elif code.startswith("```") and code.endswith("```"):
            code = code[3:-3].strip()
        
        try:
            # Create a safe local environment with useful imports
            env = {
                'bot': self.bot,
                'ctx': ctx,
                'discord': discord,
                'commands': commands,
                'asyncio': asyncio,
                'os': os,
                'aiosqlite': __import__('aiosqlite'),
                '__import__': __import__,
            }
            
            # Check if code contains await or multiple lines - if so, wrap in async function
            if 'await' in code or '\n' in code:
                # Indent all lines properly
                indented_lines = []
                for line in code.split('\n'):
                    indented_lines.append('    ' + line)
                indented_code = '\n'.join(indented_lines)
                
                # Wrap in async function
                wrapped_code = f"async def _eval_func():\n{indented_code}"
                exec(wrapped_code, env)
                result = await env['_eval_func']()
            else:
                # Single line expression without await
                try:
                    result = eval(code, env)
                    # If result is a coroutine, await it
                    if asyncio.iscoroutine(result):
                        result = await result
                except SyntaxError:
                    # If that fails, try to exec it
                    exec(code, env)
                    result = env.get('result', 'Code executed successfully (no return value)')
            
            # Format the result
            if result is None:
                output = "✅ Code executed successfully (returned None)"
            else:
                output = f"```python\n{repr(result)}\n```"
                if len(output) > 1900:
                    filename = f"eval_output_{ctx.message.id}.txt"
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self._write_file, filename, str(result))
                    await ctx.send("📊 Result:", file=discord.File(filename))
                    await loop.run_in_executor(None, os.remove, filename)
                    return
            
            await ctx.send(output)
        
        except Exception as e:
            error_msg = f"```python\n{type(e).__name__}: {str(e)}\n```"
            await ctx.send(f"❌ Error:\n{error_msg}")
            logger.exception("Error in admin command")
    
    @commands.command(name="pwd")
    @is_owner()
    async def pwd(self, ctx):
        """Show current working directory"""
        cwd = os.getcwd()
        await ctx.send(f"📁 Current directory: `{cwd}`")
    
    @commands.command(name="ls")
    @is_owner()
    async def ls(self, ctx, path: str = "."):
        """List files in a directory. Usage: !ls [path]"""
        try:
            loop = asyncio.get_event_loop()
            items = await loop.run_in_executor(None, os.listdir, path)
            
            if not items:
                await ctx.send(f"📁 `{path}` is empty")
                return
            
            # Build dirs and files lists
            def _categorize():
                dirs = []
                files = []
                for item in items:
                    full_path = os.path.join(path, item)
                    if os.path.isdir(full_path):
                        dirs.append(f"📁 {item}/")
                    elif os.path.isfile(full_path):
                        files.append(f"📄 {item}")
                return sorted(dirs) + sorted(files)
            
            items_list = await loop.run_in_executor(None, _categorize)
            output = "\n".join(items_list)
            
            if len(output) > 1900:
                filename = f"ls_output_{ctx.message.id}.txt"
                await loop.run_in_executor(None, self._write_file, filename, output)
                await ctx.send(f"📁 Contents of `{path}`:", file=discord.File(filename))
                await loop.run_in_executor(None, os.remove, filename)
            else:
                embed = discord.Embed(
                    title=f"📁 Contents of `{path}`",
                    description=output,
                    color=discord.Color.blue()
                )
                await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
    
    @commands.group(name="code", invoke_without_command=True)
    @is_owner()
    async def code(self, ctx):
        """Code management commands. Use !code help for more info."""
        await ctx.send("Use `!code help` to see all available code commands.")
    
    @code.command(name="help")
    @is_owner()
    async def code_help(self, ctx):
        """Show all code commands"""
        embed = discord.Embed(
            title="📝 Code Commands",
            description="All commands for viewing and editing code files",
            color=discord.Color.blue()
        )
        
        commands_list = [
            ("**view** `<file>`", "View file contents with syntax highlighting"),
            ("**search** `<pattern>` `[path]`", "Search for code patterns in files"),
            ("**edit** `<file>` `<line>` `[end_line]`", "Edit line(s) interactively with popup editor"),
            ("**insert** `<file>` `<line>` `<content>`", "Insert a new line at position"),
            ("**delete** `<file>` `<line>`", "Delete a specific line"),
            ("**replace** `<file>` `\"find\"` `\"replace\"` `[--all]`", "Find and replace text"),
            ("**backup** `<file>`", "Create timestamped backup"),
            ("**diff** `<file1>` `<file2>`", "Compare two files"),
            ("**find** `<file>` `<text>`", "Find specific text and show line numbers"),
        ]
        
        for cmd, desc in commands_list:
            embed.add_field(name=cmd, value=desc, inline=False)
        
        embed.set_footer(text="Example: !code edit bot.py 42")
        await ctx.send(embed=embed)
    
    @code.command(name="view", aliases=["cat", "read"])
    @is_owner()
    async def code_view(self, ctx, *, path: str):
        """View file contents. Usage: !code view <file_path>"""
        # Security check
        if not is_path_safe(path):
            await ctx.send("❌ Access to this file is blocked for security reasons.")
            return
        
        try:
            if not os.path.isfile(path):
                await ctx.send(f"❌ File not found: `{path}`")
                return
            
            # Check file size
            file_size = os.path.getsize(path)
            if file_size > 1_000_000:  # 1MB limit
                await ctx.send(f"❌ File is too large ({file_size:,} bytes). Max: 1MB")
                return
            
            loop = asyncio.get_event_loop()
            
            def _read():
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
            
            try:
                content = await loop.run_in_executor(None, _read)
            except UnicodeDecodeError:
                await ctx.send("❌ Cannot read file: binary or non-UTF-8 encoded")
                return
            
            # Determine language for syntax highlighting
            ext = os.path.splitext(path)[1].lower()
            lang_map = {
                '.py': 'python',
                '.js': 'javascript',
                '.ts': 'typescript',
                '.json': 'json',
                '.yml': 'yaml',
                '.yaml': 'yaml',
                '.md': 'markdown',
                '.sh': 'bash',
                '.sql': 'sql',
                '.html': 'html',
                '.css': 'css',
            }
            lang = lang_map.get(ext, '')
            
            # Add line numbers
            lines = content.split('\n')
            numbered_lines = []
            line_num_width = len(str(len(lines)))
            for i, line in enumerate(lines, 1):
                numbered_lines.append(f"{i:>{line_num_width}} | {line}")
            numbered_content = '\n'.join(numbered_lines)
            
            # Handle output
            if len(numbered_content) > 1900:
                filename = f"file_content_{ctx.message.id}.txt"
                await loop.run_in_executor(None, self._write_file, filename, numbered_content)
                await ctx.send(f"📄 `{path}` ({file_size:,} bytes, {len(lines)} lines):", file=discord.File(filename))
                await loop.run_in_executor(None, os.remove, filename)
            else:
                await ctx.send(f"📄 `{path}` ({len(lines)} lines):\n```{lang}\n{numbered_content}\n```")
        
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    @code.command(name="search", aliases=["grep", "find-all"])
    @is_owner()
    async def code_search(self, ctx, pattern: str, path: str = "."):
        """Search for code patterns in files. Usage: !code search "<pattern>" [path]"""
        try:
            loop = asyncio.get_event_loop()
            
            def _search():
                import re
                results = []
                
                if os.path.isfile(path):
                    files = [path]
                elif os.path.isdir(path):
                    files = []
                    for root, dirs, filenames in os.walk(path):
                        # Skip hidden and backup directories
                        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['backups', '__pycache__', 'node_modules', 'venv', '.venv']]
                        for filename in filenames:
                            if filename.endswith(('.py', '.js', '.json', '.txt', '.md', '.yml', '.yaml', '.html', '.css', '.sql')):
                                files.append(os.path.join(root, filename))
                else:
                    return None, "Invalid path"
                
                for filepath in files[:200]:  # Limit to 200 files
                    if not is_path_safe(filepath):
                        continue
                    
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            for i, line in enumerate(f, 1):
                                if re.search(pattern, line, re.IGNORECASE):
                                    results.append({
                                        'file': filepath,
                                        'line': i,
                                        'content': line.rstrip()
                                    })
                                    if len(results) >= 100:  # Limit results
                                        return results, "truncated"
                    except Exception:
                        continue
                
                return results, None
            
            results, status = await loop.run_in_executor(None, _search)
            
            if results is None:
                await ctx.send(f"❌ {status}")
                return
            
            if not results:
                await ctx.send(f"❌ No matches found for pattern: `{pattern}`")
                return
            
            # Group by file
            files_dict = {}
            for result in results:
                if result['file'] not in files_dict:
                    files_dict[result['file']] = []
                files_dict[result['file']].append(result)
            
            # Build output
            output_parts = []
            output_parts.append(f"🔍 Found {len(results)} match(es) in {len(files_dict)} file(s)")
            if status == "truncated":
                output_parts.append("(Showing first 100 matches)")
            output_parts.append("")
            
            for filepath, file_results in files_dict.items():
                output_parts.append(f"\n📄 **{filepath}** ({len(file_results)} match(es)):")
                for result in file_results[:10]:  # Max 10 per file in output
                    output_parts.append(f"  Line {result['line']}: `{result['content'][:100]}`")
                if len(file_results) > 10:
                    output_parts.append(f"  ... and {len(file_results) - 10} more")
            
            output = "\n".join(output_parts)
            
            if len(output) > 1900:
                # Create detailed file
                detailed_output = [f"Search results for: {pattern}\n{'=' * 50}\n"]
                for filepath, file_results in files_dict.items():
                    detailed_output.append(f"\n{filepath}:")
                    for result in file_results:
                        detailed_output.append(f"  {result['line']}: {result['content']}")
                
                filename = f"search_{ctx.message.id}.txt"
                await loop.run_in_executor(None, self._write_file, filename, '\n'.join(detailed_output))
                await ctx.send(f"🔍 Found {len(results)} matches (see attached file):", file=discord.File(filename))
                await loop.run_in_executor(None, os.remove, filename)
            else:
                await ctx.send(output)
        
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    @code.command(name="find")
    @is_owner()
    async def code_find(self, ctx, path: str, *, text: str):
        """Find specific text in a file and show line numbers. Usage: !code find <file> <text>"""
        # Security check
        if not is_path_safe(path):
            await ctx.send("❌ Access to this file is blocked for security reasons.")
            return
        
        try:
            if not os.path.isfile(path):
                await ctx.send(f"❌ File not found: `{path}`")
                return
            
            loop = asyncio.get_event_loop()
            
            def _find():
                matches = []
                with open(path, 'r', encoding='utf-8') as f:
                    for i, line in enumerate(f, 1):
                        if text.lower() in line.lower():
                            matches.append((i, line.rstrip()))
                return matches
            
            matches = await loop.run_in_executor(None, _find)
            
            if not matches:
                await ctx.send(f"❌ Text not found in `{path}`")
                return
            
            embed = discord.Embed(
                title=f"🔍 Found in `{os.path.basename(path)}`",
                description=f"Found {len(matches)} occurrence(s) of: `{text}`",
                color=discord.Color.green()
            )
            
            # Show matches
            for line_num, line_content in matches[:15]:  # Show max 15
                # Highlight the match
                highlighted = line_content.replace(text, f"**{text}**")
                if len(highlighted) > 100:
                    # Find the match position and show context
                    pos = line_content.lower().find(text.lower())
                    start = max(0, pos - 40)
                    end = min(len(line_content), pos + len(text) + 40)
                    snippet = line_content[start:end]
                    if start > 0:
                        snippet = "..." + snippet
                    if end < len(line_content):
                        snippet = snippet + "..."
                    highlighted = snippet.replace(text, f"**{text}**")
                
                embed.add_field(
                    name=f"Line {line_num}",
                    value=f"`{highlighted}`",
                    inline=False
                )
            
            if len(matches) > 15:
                embed.set_footer(text=f"Showing first 15 of {len(matches)} matches")
            
            await ctx.send(embed=embed)
        
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
        
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    @code.command(name="edit")
    @is_owner()
    async def code_edit(self, ctx, path: str, line_start: int, line_end: Optional[int] = None):
        """Edit line(s) in a file interactively. Usage: !code edit <file> <line_num> OR !code edit <file> <start_line> <end_line>"""
        # Security check
        if not is_path_safe(path):
            await ctx.send("❌ Access to this file is blocked for security reasons.")
            return
        
        try:
            if not os.path.isfile(path):
                await ctx.send(f"❌ File not found: `{path}`")
                return
            
            # If no end line, edit single line
            if line_end is None:
                line_end = line_start
            
            loop = asyncio.get_event_loop()
            
            def _read_lines():
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                # Validate line numbers
                if line_start < 1 or line_start > len(lines):
                    return None, None, f"Line {line_start} is out of range (file has {len(lines)} lines)"
                if line_end < line_start or line_end > len(lines):
                    return None, None, f"Line {line_end} is out of range"
                
                # Get the lines to edit
                selected_lines = ''.join(lines[line_start-1:line_end]).rstrip()
                
                return lines, selected_lines, None
            
            lines, selected_lines, error = await loop.run_in_executor(None, _read_lines)
            
            if error:
                await ctx.send(f"❌ {error}")
                return
            
            # Create modal for editing
            class EditModal(discord.ui.Modal, title=f"Edit {os.path.basename(path)}"):
                def __init__(self, parent_cog, path, lines, line_start, line_end, selected_lines):
                    super().__init__()
                    self.cog = parent_cog
                    self.path = path
                    self.lines = lines
                    self.line_start = line_start
                    self.line_end = line_end
                    
                    # Add text input with current content
                    self.code_input = discord.ui.TextInput(
                        label=f"Lines {line_start}-{line_end}" if line_start != line_end else f"Line {line_start}",
                        style=discord.TextStyle.paragraph,
                        default=selected_lines,
                        required=True,
                        max_length=4000
                    )
                    self.add_item(self.code_input)
                
                async def on_submit(self, interaction: discord.Interaction):
                    new_content = self.code_input.value
                    
                    loop = asyncio.get_event_loop()
                    
                    def _write():
                        # Replace the lines
                        new_lines = new_content.split('\n')
                        # Ensure newlines at end
                        new_lines = [line + '\n' if not line.endswith('\n') else line for line in new_lines]
                        
                        # Remove the old lines and insert new ones
                        self.lines[self.line_start-1:self.line_end] = new_lines
                        
                        # Write back
                        with open(self.path, 'w', encoding='utf-8') as f:
                            f.writelines(self.lines)
                    
                    try:
                        await loop.run_in_executor(None, _write)
                        
                        embed = discord.Embed(
                            title=f"✅ Edited `{os.path.basename(self.path)}`",
                            description=f"Lines {self.line_start}-{self.line_end}" if self.line_start != self.line_end else f"Line {self.line_start}",
                            color=discord.Color.green()
                        )
                        
                        # Show a preview if not too long
                        if len(new_content) < 1000:
                            embed.add_field(name="New Content", value=f"```python\n{new_content}\n```", inline=False)
                        else:
                            embed.add_field(name="New Content", value=f"```\n{new_content[:500]}...\n(truncated)\n```", inline=False)
                        
                        await interaction.response.send_message(embed=embed)
                    except Exception as e:
                        await interaction.response.send_message(f"❌ Error saving: {str(e)}", ephemeral=True)
            
            # Create a view with button to open modal
            class EditView(discord.ui.View):
                def __init__(self, cog, path, lines, line_start, line_end, selected_lines):
                    super().__init__(timeout=300)
                    self.cog = cog
                    self.path = path
                    self.lines = lines
                    self.line_start = line_start
                    self.line_end = line_end
                    self.selected_lines = selected_lines
                
                @discord.ui.button(label="✏️ Edit Code", style=discord.ButtonStyle.primary)
                async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user.id != ADMIN_USER_ID:
                        await interaction.response.send_message("❌ Only the bot owner can edit files.", ephemeral=True)
                        return
                    
                    modal = EditModal(self.cog, self.path, self.lines.copy(), self.line_start, self.line_end, self.selected_lines)
                    await interaction.response.send_modal(modal)
                
                @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
                async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user.id != ADMIN_USER_ID:
                        await interaction.response.send_message("❌ Only the bot owner can use this.", ephemeral=True)
                        return
                    await interaction.response.send_message("✅ Edit cancelled.", ephemeral=True)
                    self.stop()
            
            # Send message with current code
            embed = discord.Embed(
                title=f"📝 Ready to edit `{os.path.basename(path)}`",
                description=f"Lines {line_start}-{line_end}" if line_start != line_end else f"Line {line_start}",
                color=discord.Color.blue()
            )
            
            # Show current content
            if len(selected_lines) < 1000:
                embed.add_field(name="Current Content", value=f"```python\n{selected_lines}\n```", inline=False)
            else:
                embed.add_field(name="Current Content", value=f"```python\n{selected_lines[:500]}...\n(truncated, will show full in editor)\n```", inline=False)
            
            embed.set_footer(text="Click 'Edit Code' to open the editor")
            
            view = EditView(self, path, lines, line_start, line_end, selected_lines)
            await ctx.send(embed=embed, view=view)
        
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    @code.command(name="insert")
    @is_owner()
    async def code_insert(self, ctx, path: str, line_num: int, *, content: str):
        """Insert a new line at a specific position. Usage: !code insert <file> <line_number> <content>"""
        # Security check
        if not is_path_safe(path):
            await ctx.send("❌ Access to this file is blocked for security reasons.")
            return
        
        try:
            if not os.path.isfile(path):
                await ctx.send(f"❌ File not found: `{path}`")
                return
            
            loop = asyncio.get_event_loop()
            
            def _insert():
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                # Validate line number
                if line_num < 1 or line_num > len(lines) + 1:
                    return f"Line {line_num} is out of range (file has {len(lines)} lines)"
                
                # Insert new line
                lines.insert(line_num - 1, content + '\n')
                
                # Write back
                with open(path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                
                return None
            
            error = await loop.run_in_executor(None, _insert)
            
            if error:
                await ctx.send(f"❌ {error}")
                return
            
            await ctx.send(f"✅ Inserted line {line_num} in `{path}`:\n```{content}```")
        
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    @code.command(name="delete", aliases=["del"])
    @is_owner()
    async def code_delete(self, ctx, path: str, line_num: int):
        """Delete a specific line from a file. Usage: !code delete <file> <line_number>"""
        # Security check
        if not is_path_safe(path):
            await ctx.send("❌ Access to this file is blocked for security reasons.")
            return
        
        try:
            if not os.path.isfile(path):
                await ctx.send(f"❌ File not found: `{path}`")
                return
            
            loop = asyncio.get_event_loop()
            
            def _delete():
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                # Validate line number
                if line_num < 1 or line_num > len(lines):
                    return None, f"Line {line_num} is out of range (file has {len(lines)} lines)"
                
                # Store deleted line for confirmation
                deleted_line = lines[line_num - 1].rstrip()
                
                # Delete line
                del lines[line_num - 1]
                
                # Write back
                with open(path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                
                return deleted_line, None
            
            deleted_line, error = await loop.run_in_executor(None, _delete)
            
            if error:
                await ctx.send(f"❌ {error}")
                return
            
            await ctx.send(f"✅ Deleted line {line_num} from `{path}`:\n```{deleted_line}```")
        
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    @code.command(name="replace")
    @is_owner()
    async def code_replace(self, ctx, path: str, find: str, replace: str, *, options: str = ""):
        """Find and replace text in a file. Usage: !code replace <file> "<find>" "<replace>" [--all]"""
        # Security check
        if not is_path_safe(path):
            await ctx.send("❌ Access to this file is blocked for security reasons.")
            return
        
        try:
            if not os.path.isfile(path):
                await ctx.send(f"❌ File not found: `{path}`")
                return
            
            replace_all = "--all" in options.lower()
            
            loop = asyncio.get_event_loop()
            
            def _replace():
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Count occurrences
                count = content.count(find)
                if count == 0:
                    return 0, None
                
                # Replace
                if replace_all:
                    new_content = content.replace(find, replace)
                else:
                    new_content = content.replace(find, replace, 1)
                
                # Write back
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                
                return count, 1 if not replace_all else count
            
            total_found, replaced = await loop.run_in_executor(None, _replace)
            
            if total_found == 0:
                await ctx.send(f"❌ Text not found in `{path}`")
                return
            
            msg = f"✅ Replaced {replaced} occurrence(s) in `{path}`"
            if not replace_all and total_found > 1:
                msg += f"\n(Found {total_found} total occurrences. Use `--all` to replace all)"
            
            embed = discord.Embed(
                title=msg,
                color=discord.Color.green()
            )
            embed.add_field(name="Find", value=f"```{find}```", inline=False)
            embed.add_field(name="Replace", value=f"```{replace}```", inline=False)
            await ctx.send(embed=embed)
        
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    @code.command(name="backup")
    @is_owner()
    async def code_backup(self, ctx, path: str):
        """Create a backup of a file. Usage: !code backup <file>"""
        # Security check
        if not is_path_safe(path):
            await ctx.send("❌ Access to this file is blocked for security reasons.")
            return
        
        try:
            if not os.path.isfile(path):
                await ctx.send(f"❌ File not found: `{path}`")
                return
            
            # Create backup filename
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{path}.backup_{timestamp}"
            
            loop = asyncio.get_event_loop()
            
            def _backup():
                import shutil
                shutil.copy2(path, backup_path)
            
            await loop.run_in_executor(None, _backup)
            await ctx.send(f"✅ Created backup: `{backup_path}`")
        
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    @code.command(name="diff")
    @is_owner()
    async def code_diff(self, ctx, path1: str, path2: str):
        """Compare two files. Usage: !code diff <file1> <file2>"""
        # Security check
        if not is_path_safe(path1) or not is_path_safe(path2):
            await ctx.send("❌ Access to one or more files is blocked for security reasons.")
            return
        
        try:
            if not os.path.isfile(path1):
                await ctx.send(f"❌ File not found: `{path1}`")
                return
            if not os.path.isfile(path2):
                await ctx.send(f"❌ File not found: `{path2}`")
                return
            
            loop = asyncio.get_event_loop()
            
            def _diff():
                import difflib
                
                with open(path1, 'r', encoding='utf-8') as f:
                    lines1 = f.readlines()
                with open(path2, 'r', encoding='utf-8') as f:
                    lines2 = f.readlines()
                
                diff = difflib.unified_diff(
                    lines1, lines2,
                    fromfile=path1,
                    tofile=path2,
                    lineterm=''
                )
                
                return '\n'.join(diff)
            
            diff_output = await loop.run_in_executor(None, _diff)
            
            if not diff_output:
                await ctx.send("✅ Files are identical")
                return
            
            if len(diff_output) > 1900:
                filename = f"diff_{ctx.message.id}.txt"
                await loop.run_in_executor(None, self._write_file, filename, diff_output)
                await ctx.send("📊 Diff:", file=discord.File(filename))
                await loop.run_in_executor(None, os.remove, filename)
            else:
                await ctx.send(f"```diff\n{diff_output}\n```")
        
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")
    
    @commands.command(name="grep")
    @is_owner()
    async def grep(self, ctx, pattern: str, path: str = "."):
        """Search for text in files. Usage: !grep "<pattern>" [path]"""
        try:
            loop = asyncio.get_event_loop()
            
            def _grep():
                import re
                results = []
                
                if os.path.isfile(path):
                    files = [path]
                elif os.path.isdir(path):
                    files = []
                    for root, dirs, filenames in os.walk(path):
                        # Skip hidden and backup directories
                        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['backups', '__pycache__', 'node_modules']]
                        for filename in filenames:
                            if filename.endswith(('.py', '.js', '.json', '.txt', '.md', '.yml', '.yaml')):
                                files.append(os.path.join(root, filename))
                else:
                    return None, "Invalid path"
                
                for filepath in files[:100]:  # Limit to 100 files
                    if not is_path_safe(filepath):
                        continue
                    
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            for i, line in enumerate(f, 1):
                                if re.search(pattern, line):
                                    results.append(f"{filepath}:{i}: {line.rstrip()}")
                                    if len(results) >= 50:  # Limit results
                                        return results, "truncated"
                    except Exception:
                        continue
                
                return results, None
            
            results, status = await loop.run_in_executor(None, _grep)
            
            if results is None:
                await ctx.send(f"❌ {status}")
                return
            
            if not results:
                await ctx.send(f"❌ No matches found for pattern: `{pattern}`")
                return
            
            output = "\n".join(results)
            if status == "truncated":
                output += "\n... (truncated, showing first 50 matches)"
            
            if len(output) > 1900:
                filename = f"grep_{ctx.message.id}.txt"
                await loop.run_in_executor(None, self._write_file, filename, output)
                await ctx.send(f"🔍 Search results for `{pattern}`:", file=discord.File(filename))
                await loop.run_in_executor(None, os.remove, filename)
            else:
                await ctx.send(f"🔍 Search results for `{pattern}`:\n```\n{output}\n```")
        
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
            logger.exception("Error in admin command")

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))