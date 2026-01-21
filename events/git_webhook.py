import discord
from discord.ext import commands
from aiohttp import web
import hmac
import hashlib
import os
from dotenv import load_dotenv

load_dotenv()

COMMIT_CHANNEL_IDS = [876777562599194644, 1437941632849940563, 1424145004976275617]
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
# Updated port to be 8000 to prevent conflicts (should work)
# I think the port itself wants me dead
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", 8000))

class GitWebhook(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.app = web.Application()
        self.app.router.add_post('/webhook', self.handle_webhook)
        self.app.router.add_get('/health', self.health_check)
        self.runner = None
        self.site = None
        
    async def cog_load(self):
        """Start the webhook server when cog loads."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '0.0.0.0', WEBHOOK_PORT)
        await self.site.start()
        print(f"✅ Git webhook server started on port {WEBHOOK_PORT}")
        print(f"   Configure GitHub to send webhooks to: http://185.187.170.61:{WEBHOOK_PORT}/webhook")
        print(f"   Sending notifications to {len(COMMIT_CHANNEL_IDS)} channel(s)")
    
    async def cog_unload(self):
        """Stop the webhook server when cog unloads."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        print("🛑 Git webhook server stopped")
    
    def verify_signature(self, payload_body, signature_header):
        """Verify GitHub webhook signature for security."""
        if not WEBHOOK_SECRET:
            return True
        
        hash_object = hmac.new(
            WEBHOOK_SECRET.encode('utf-8'),
            msg=payload_body,
            digestmod=hashlib.sha256
        )
        expected_signature = "sha256=" + hash_object.hexdigest()
        return hmac.compare_digest(expected_signature, signature_header)
    
    async def health_check(self, request):
        """Health check endpoint."""
        return web.json_response({"status": "healthy"})
    
    async def handle_webhook(self, request):
        """Handle incoming Git webhook from GitHub/GitLab."""
        try:
            # Verify signature if secret is configured
            if WEBHOOK_SECRET:
                signature = request.headers.get('X-Hub-Signature-256', '')
                body = await request.read()
                if not self.verify_signature(body, signature):
                    return web.json_response({"error": "Invalid signature"}, status=403)
                data = await request.json()
            else:
                data = await request.json()
            
            # Handle GitHub ping event (test from GitHub)
            if 'zen' in data and 'hook_id' in data:
                print("✅ Received GitHub ping event - webhook is configured correctly!")
                return web.json_response({"status": "pong"}, status=200)
            
            # Get all Discord channels
            channels = []
            for channel_id in COMMIT_CHANNEL_IDS:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    channels.append(channel)
                else:
                    print(f"⚠️ Channel {channel_id} not found!")
            
            if not channels:
                print(f"❌ No valid channels found!")
                return web.json_response({"error": "No channels found"}, status=500)
            
            # Handle GitHub push events
            if 'commits' in data and 'repository' in data:
                await self.handle_github_push(data, channels)
                return web.json_response({"status": "success"}, status=200)
            
            # Handle GitLab push events
            elif 'project' in data and 'commits' in data:
                await self.handle_gitlab_push(data, channels)
                return web.json_response({"status": "success"}, status=200)
            
            print(f"⚠️ Unknown webhook format. Keys in data: {list(data.keys())}")
            return web.json_response({"error": "Unknown webhook format"}, status=400)
            
        except Exception as e:
            print(f"❌ Webhook error: {e}")
            import traceback
            traceback.print_exc()
            return web.json_response({"error": str(e)}, status=500)
    
    async def handle_github_push(self, data, channels):
        """Handle GitHub push webhook."""
        repo_name = data['repository']['full_name']
        repo_url = data['repository']['html_url']
        branch = data['ref'].split('/')[-1]
        pusher = data['pusher']['name']
        commits = data['commits']
        compare_url = data.get('compare', '')
        
        if not commits:
            return
        
        # For single commit, use fields for better formatting
        if len(commits) == 1:
            commit = commits[0]
            short_sha = commit['id'][:7]
            message = commit['message']
            author = commit['author']['name']
            url = commit['url']
            
            embed = discord.Embed(
                title=f"📝 [{repo_name}:{branch}] New commit",
                url=compare_url if compare_url else repo_url,
                color=discord.Color.blue()
            )
            embed.add_field(name="Commit", value=f"[`{short_sha}`]({url})", inline=True)
            embed.add_field(name="Author", value=author, inline=True)
            embed.add_field(name="Message", value=message, inline=False)
            embed.set_author(name=pusher, icon_url="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png")
            embed.set_footer(text="GitHub")
        else:
            # For multiple commits, use description with truncated messages
            commit_lines = []
            for commit in commits[:10]:
                short_sha = commit['id'][:7]
                message = commit['message'].split('\n')[0]  # First line only
                if len(message) > 72:
                    message = message[:69] + "..."
                author = commit['author']['name']
                url = commit['url']
                commit_lines.append(f"[`{short_sha}`]({url}) {message} - {author}")
            
            embed = discord.Embed(
                title=f"📝 [{repo_name}:{branch}] {len(commits)} new commits",
                url=compare_url if compare_url else repo_url,
                description="\n".join(commit_lines),
                color=discord.Color.blue()
            )
            
            if len(commits) > 10:
                embed.description += f"\n\n*...and {len(commits) - 10} more commit(s)*"
            
            embed.set_author(name=pusher, icon_url="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png")
            embed.set_footer(text="GitHub")
        
        # Send to all Discord channels
        for channel in channels:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"❌ Failed to send to channel {channel.id}: {e}")
    
    async def handle_gitlab_push(self, data, channels):
        """Handle GitLab push webhook."""
        repo_name = data['project']['path_with_namespace']
        repo_url = data['project']['web_url']
        branch = data['ref'].split('/')[-1]
        pusher = data['user_name']
        commits = data['commits']
        
        if not commits:
            return
        
        # For single commit, use fields for better formatting
        if len(commits) == 1:
            commit = commits[0]
            short_sha = commit['id'][:7]
            message = commit['message']
            author = commit['author']['name']
            url = commit['url']
            
            embed = discord.Embed(
                title=f"📝 [{repo_name}:{branch}] New commit",
                url=repo_url,
                color=0xFC6D26  # GitLab orange
            )
            embed.add_field(name="Commit", value=f"[`{short_sha}`]({url})", inline=True)
            embed.add_field(name="Author", value=author, inline=True)
            embed.add_field(name="Message", value=message, inline=False)
            embed.set_author(name=pusher)
            embed.set_footer(text="GitLab")
        else:
            # For multiple commits, use description with truncated messages
            commit_lines = []
            for commit in commits[:10]:
                short_sha = commit['id'][:7]
                message = commit['message'].split('\n')[0]
                if len(message) > 72:
                    message = message[:69] + "..."
                author = commit['author']['name']
                url = commit['url']
                commit_lines.append(f"[`{short_sha}`]({url}) {message} - {author}")
            
            embed = discord.Embed(
                title=f"📝 [{repo_name}:{branch}] {len(commits)} new commits",
                url=repo_url,
                description="\n".join(commit_lines),
                color=0xFC6D26  # GitLab orange
            )
            
            if len(commits) > 10:
                embed.description += f"\n\n*...and {len(commits) - 10} more commit(s)*"
            
            embed.set_author(name=pusher)
            embed.set_footer(text="GitLab")
        
        # Send to all Discord channels
        for channel in channels:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"❌ Failed to send to channel {channel.id}: {e}")

async def setup(bot):
    await bot.add_cog(GitWebhook(bot))