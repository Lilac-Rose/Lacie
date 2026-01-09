import discord
from discord.ext import commands
import aiosqlite
import asyncio
import os
import glob
from typing import Optional
import traceback

ADMIN_USER_ID = 252130669919076352

def is_owner():
    """Check if the user is the bot owner"""
    async def predicate(ctx):
        return ctx.author.id == ADMIN_USER_ID
    return commands.check(predicate)

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
        print(f"Discovered databases: {list(self.db_connections.keys())}")
    
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
            traceback.print_exc()
    
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
            traceback.print_exc()
    
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
            traceback.print_exc()
    
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
            traceback.print_exc()
    
    @commands.command(name="terminal", aliases=["term", "sh"])
    @is_owner()
    async def terminal(self, ctx, *, command: str):
        """Execute a shell command. Usage: !terminal <command>"""
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
            traceback.print_exc()
    
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
            traceback.print_exc()
    
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

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))