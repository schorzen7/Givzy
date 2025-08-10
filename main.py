import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
import json
import random
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from typing import Optional
import re
import logging
from keep_alive import keep_alive

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

# Database channel ID
DATABASE_CHANNEL_ID = 1393415294663528529

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}

async def load_database():
    """Load giveaway data from the database channel."""
    global giveaways
    try:
        db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
        if not db_channel:
            logging.error(f"Database channel {DATABASE_CHANNEL_ID} not found!")
            return

        # Look for the latest database message
        async for message in db_channel.history(limit=100):
            if message.author == bot.user and message.content.startswith("```json"):
                try:
                    # Extract JSON from code block
                    json_content = message.content[7:-3]  # Remove ```json and ```
                    giveaways = json.loads(json_content)
                    logging.info(f"Loaded {len(giveaways)} giveaways from database channel.")
                    return
                except json.JSONDecodeError:
                    continue
        
        logging.info("No valid database found in channel, starting with empty database.")
        giveaways = {}
    except Exception as e:
        logging.error(f"Error loading database: {e}")
        giveaways = {}

async def save_database():
    """Save giveaway data to the database channel."""
    try:
        db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
        if not db_channel:
            logging.error(f"Database channel {DATABASE_CHANNEL_ID} not found!")
            return

        # Create JSON content
        json_content = json.dumps(giveaways, indent=2)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        message_content = f"```json\n{json_content}\n```"
        embed = discord.Embed(
            title="🗄️ Giveaway Database Backup",
            description=f"**Total Giveaways:** {len(giveaways)}\n**Last Updated:** {timestamp}",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        
        # Count active giveaways per server
        server_stats = {}
        active_count = 0
        for giveaway_id, data in giveaways.items():
            if data.get("status") == "active":
                active_count += 1
                server_id = data.get("server_id", "Unknown")
                server_stats[server_id] = server_stats.get(server_id, 0) + 1
        
        embed.add_field(name="Active Giveaways", value=str(active_count), inline=True)
        embed.add_field(name="Servers", value=str(len(server_stats)), inline=True)
        
        await db_channel.send(content=message_content, embed=embed)
        logging.info("Database saved to channel.")
        
    except Exception as e:
        logging.error(f"Error saving database: {e}")

class JoinView(View):
    """A view for joining giveaways."""
    def __init__(self, message_id: str):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green, custom_id="join_button")
    async def join(self, interaction: discord.Interaction, button: Button):
        """Callback for the join button."""
        user_id = str(interaction.user.id)
        giveaway_data = giveaways.get(self.message_id)

        if not giveaway_data:
            await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
            return

        if giveaway_data.get("status") != "active":
            await interaction.response.send_message("❌ This giveaway is not active.", ephemeral=True)
            return

        # Verify this is the correct server
        if giveaway_data.get("server_id") != interaction.guild.id:
            await interaction.response.send_message("❌ This giveaway is not for this server.", ephemeral=True)
            return

        if "participants" not in giveaway_data:
            giveaway_data["participants"] = []

        if user_id in giveaway_data["participants"]:
            await interaction.response.send_message("❌ You already joined this giveaway!", ephemeral=True)
            return

        # Check required role if specified
        required_role_id = giveaway_data.get("required_role")
        if required_role_id:
            if not interaction.guild:
                await interaction.response.send_message("❌ Cannot verify role outside of a guild.", ephemeral=True)
                return
            role = interaction.guild.get_role(required_role_id)
            member = interaction.user if isinstance(interaction.user, discord.Member) else None
            if role and member and role not in member.roles:
                await interaction.response.send_message(f"🚫 You must have the role {role.mention} to join.", ephemeral=True)
                return

        giveaway_data["participants"].append(user_id)
        giveaways[self.message_id] = giveaway_data
        await save_database()
        await interaction.response.send_message("✅ You have joined the giveaway!", ephemeral=True)

        # Update participant count in embed
        try:
            updated_embed = interaction.message.embeds[0]
            description = updated_embed.description
            # Update participant count
            lines = description.split('\n')
            for i, line in enumerate(lines):
                if line.startswith("👥 **Participants:**"):
                    lines[i] = f"👥 **Participants:** {len(giveaway_data['participants'])}"
                    break
            updated_embed.description = '\n'.join(lines)
            await interaction.edit_original_response(embed=updated_embed)
        except:
            pass  # If we can't update, it's not critical

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    prize="What is the prize?",
    winners="How many winners?",
    donor="The name of the giveaway donor",
    role="Optional role required to join"
)
async def giveaway(interaction: discord.Interaction, prize: str, winners: int, donor: str, role: Optional[discord.Role] = None):
    """Starts a new giveaway."""
    if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message("❌ Giveaways can only be started in text channels!", ephemeral=True)
        return

    if interaction.guild is None:
        await interaction.response.send_message("❌ This command can only be used in a server!", ephemeral=True)
        return

    description_parts = [
        f"🎁 **Prize:** {prize}",
        f"✨ **Donor:** {donor}",
        f"🏆 **Winners:** {winners}",
        f"👥 **Participants:** 0",
        f"🏠 **Server:** {interaction.guild.name}"
    ]

    if role is not None:
        description_parts.append(f"🛡️ **Required Role:** {role.mention}")

    embed = discord.Embed(
        title="🎉✨ GIVEAWAY! ✨🎉",
        description="\n".join(description_parts),
        color=discord.Color.from_rgb(255, 105, 180)
    )
    embed.set_footer(text="Click the 🎉 button to enter!")

    view = JoinView(message_id="temp_placeholder")

    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()

    message_id_str = str(message.id)
    view.message_id = message_id_str
    bot.add_view(view, message_id=message.id)

    giveaways[message_id_str] = {
        "server_id": interaction.guild.id,
        "server_name": interaction.guild.name,
        "channel_id": interaction.channel.id,
        "prize": prize,
        "winners": winners,
        "participants": [],
        "donor_name": donor,
        "required_role": role.id if role is not None else None,
        "status": "active",
        "created_by": interaction.user.id,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await save_database()
    logging.info(f"Giveaway {message_id_str} created in {interaction.guild.name} ({interaction.guild.id})")

@tree.command(name="endgiveaway", description="End a giveaway and pick winners")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(message_id="The message ID of the giveaway to end")
async def end_giveaway(interaction: discord.Interaction, message_id: str):
    """Manually end a giveaway and pick winners."""
    await interaction.response.defer(ephemeral=True)

    giveaway_data = giveaways.get(message_id)
    if not giveaway_data:
        await interaction.followup.send("❌ Giveaway not found.", ephemeral=True)
        return

    if giveaway_data.get("status") != "active":
        await interaction.followup.send("❌ This giveaway is not active.", ephemeral=True)
        return

    # Verify this is the correct server
    if giveaway_data.get("server_id") != interaction.guild.id:
        await interaction.followup.send("❌ This giveaway is not from this server.", ephemeral=True)
        return

    participants = giveaway_data.get("participants", [])
    if not participants:
        await interaction.followup.send("❌ No one participated in this giveaway.", ephemeral=True)
        giveaway_data["status"] = "ended"
        giveaway_data["ended_at"] = datetime.now(timezone.utc).isoformat()
        giveaway_data["ended_by"] = interaction.user.id
        giveaways[message_id] = giveaway_data
        await save_database()
        return

    # Pick winners
    winners_count = min(len(participants), giveaway_data["winners"])
    winner_ids = random.sample(participants, winners_count)
    mentions = " ".join(f"<@{uid}>" for uid in winner_ids)

    # Update giveaway status
    giveaway_data["status"] = "ended"
    giveaway_data["ended_at"] = datetime.now(timezone.utc).isoformat()
    giveaway_data["ended_by"] = interaction.user.id
    giveaway_data["winner_ids"] = winner_ids
    giveaways[message_id] = giveaway_data
    await save_database()

    # Try to update the original message
    channel = bot.get_channel(giveaway_data["channel_id"])
    if channel and isinstance(channel, (discord.TextChannel, discord.Thread)):
        try:
            original_message = await channel.fetch_message(int(message_id))
            
            # Update embed
            ended_embed = discord.Embed(
                title="🎉 GIVEAWAY ENDED! 🎉",
                description=f"🎁 **Prize:** {giveaway_data['prize']}\n"
                           f"✨ **Donor:** {giveaway_data['donor_name']}\n"
                           f"🏆 **Winners:** {mentions}\n"
                           f"👥 **Total Participants:** {len(participants)}",
                color=discord.Color.gold()
            )
            await original_message.edit(embed=ended_embed, view=None)
            
            # Send winner announcement
            await original_message.reply(f"🎉 Giveaway ended! Congratulations {mentions}!\nPrize: **{giveaway_data['prize']}**")
            
        except (discord.NotFound, discord.Forbidden):
            pass  # Message might be deleted or no permissions

    await interaction.followup.send(f"✅ Giveaway ended! Winners: {mentions}", ephemeral=True)
    logging.info(f"Giveaway {message_id} ended in {interaction.guild.name} with {len(winner_ids)} winners")

@tree.command(name="cancelgiveaway", description="Cancel an active giveaway")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(message_id="The message ID of the giveaway to cancel")
async def cancel_giveaway(interaction: discord.Interaction, message_id: str):
    """Cancel a giveaway."""
    await interaction.response.defer(ephemeral=True)

    giveaway_data = giveaways.get(message_id)
    if not giveaway_data:
        await interaction.followup.send("❌ Giveaway not found.", ephemeral=True)
        return

    if giveaway_data.get("status") != "active":
        await interaction.followup.send("❌ This giveaway is not active.", ephemeral=True)
        return

    # Verify this is the correct server
    if giveaway_data.get("server_id") != interaction.guild.id:
        await interaction.followup.send("❌ This giveaway is not from this server.", ephemeral=True)
        return

    giveaway_data["status"] = "cancelled"
    giveaway_data["cancelled_at"] = datetime.now(timezone.utc).isoformat()
    giveaway_data["cancelled_by"] = interaction.user.id
    giveaways[message_id] = giveaway_data
    await save_database()

    # Try to update the original message
    channel = bot.get_channel(giveaway_data["channel_id"])
    if channel and isinstance(channel, (discord.TextChannel, discord.Thread)):
        try:
            original_message = await channel.fetch_message(int(message_id))
            cancelled_embed = discord.Embed(
                title="🚫 GIVEAWAY CANCELLED 🚫",
                description=f"The giveaway for **{giveaway_data['prize']}** has been cancelled by {interaction.user.mention}.",
                color=discord.Color.red()
            )
            await original_message.edit(embed=cancelled_embed, view=None)
        except (discord.NotFound, discord.Forbidden):
            pass

    await interaction.followup.send("✅ Giveaway cancelled successfully.", ephemeral=True)
    logging.info(f"Giveaway {message_id} cancelled in {interaction.guild.name}")

@tree.command(name="giveawaystats", description="View giveaway statistics for this server")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_stats(interaction: discord.Interaction):
    """Show giveaway statistics for the current server."""
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server!", ephemeral=True)
        return

    server_giveaways = {k: v for k, v in giveaways.items() if v.get("server_id") == interaction.guild.id}
    
    total = len(server_giveaways)
    active = sum(1 for g in server_giveaways.values() if g.get("status") == "active")
    ended = sum(1 for g in server_giveaways.values() if g.get("status") == "ended")
    cancelled = sum(1 for g in server_giveaways.values() if g.get("status") == "cancelled")

    embed = discord.Embed(
        title=f"📊 Giveaway Statistics - {interaction.guild.name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="🎉 Total Giveaways", value=str(total), inline=True)
    embed.add_field(name="✅ Active", value=str(active), inline=True)
    embed.add_field(name="🏆 Ended", value=str(ended), inline=True)
    embed.add_field(name="🚫 Cancelled", value=str(cancelled), inline=True)

    # Show recent giveaways
    recent_giveaways = sorted(
        [(k, v) for k, v in server_giveaways.items()],
        key=lambda x: x[1].get("created_at", ""),
        reverse=True
    )[:5]

    if recent_giveaways:
        recent_text = ""
        for msg_id, data in recent_giveaways:
            status_emoji = {"active": "🟢", "ended": "🔴", "cancelled": "⚫"}.get(data.get("status"), "❓")
            recent_text += f"{status_emoji} **{data['prize']}** - {data.get('status', 'unknown').title()}\n"
        embed.add_field(name="🕒 Recent Giveaways", value=recent_text or "None", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.event
async def on_ready():
    """Event handler for when the bot is ready."""
    logging.info(f"Logged in as {bot.user}")
    
    # Load database from channel
    await load_database()
    
    try:
        synced = await tree.sync()
        logging.info(f"Synced {len(synced)} commands.")
    except Exception as e:
        logging.error(f"Failed to sync commands: {e}")

    # Re-attach views for active giveaways
    active_count = 0
    for message_id, data in giveaways.items():
        if data.get("status") == "active":
            try:
                bot.add_view(JoinView(message_id=message_id), message_id=int(message_id))
                active_count += 1
            except:
                pass
    
    logging.info(f"Re-attached {active_count} active giveaway views across all servers.")
    logging.info(f"Bot is ready! Managing {len(giveaways)} total giveaways across multiple servers.")

@bot.event
async def on_guild_join(guild):
    """Log when the bot joins a new server."""
    logging.info(f"Joined new server: {guild.name} ({guild.id}) with {guild.member_count} members")

@bot.event
async def on_guild_remove(guild):
    """Log when the bot leaves a server."""
    logging.info(f"Left server: {guild.name} ({guild.id})")

# Get Discord token
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is not set in the environment.")

keep_alive()
bot.run(DISCORD_TOKEN)
