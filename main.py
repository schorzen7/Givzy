import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import json
import random
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from typing import Optional, Dict, List
import re
import logging
import asyncio
import hashlib
from keep_alive import keep_alive

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('giveaway_bot.log'),
        logging.StreamHandler()
    ]
)

load_dotenv()

# Database channel ID
DATABASE_CHANNEL_ID = 1393415294663528529

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Global data structures
giveaways = {}
giveaway_templates = {}
blacklisted_users = {}
database_loaded = False

# Constants for better data management
MAX_RETRIES = 3
SAVE_DELAY = 10  # seconds before saving (to batch multiple changes)
DATABASE_VERSION = "2.1"

async def validate_message_id(message_id: str) -> bool:
    """Validate that message_id is a valid Discord message ID"""
    try:
        mid = int(message_id)
        return 17 <= len(str(mid)) <= 20
    except ValueError:
        return False

async def check_user_eligibility(user: discord.Member, giveaway_data: dict) -> tuple[bool, str]:
    """Check if user meets all requirements to join giveaway"""
    now = datetime.now(timezone.utc)
    
    # Check if user is blacklisted
    server_blacklist = blacklisted_users.get(str(user.guild.id), {})
    if str(user.id) in server_blacklist:
        reason = server_blacklist[str(user.id)].get('reason', 'No reason provided')
        return False, f"🚫 You are blacklisted from giveaways. Reason: {reason}"
    
    # Check required role
    required_role_id = giveaway_data.get("required_role")
    if required_role_id:
        role = user.guild.get_role(required_role_id)
        if role and role not in user.roles:
            return False, f"🛡️ You must have the role {role.mention} to join."
    
    # Check minimum account age
    min_account_days = giveaway_data.get("min_account_age_days", 0)
    if min_account_days > 0:
        account_age = (now - user.created_at.replace(tzinfo=timezone.utc)).days
        if account_age < min_account_days:
            return False, f"⏰ Your account must be at least {min_account_days} days old to join."
    
    # Check minimum server join time
    min_server_days = giveaway_data.get("min_server_days", 0)
    if min_server_days > 0 and user.joined_at:
        server_time = (now - user.joined_at.replace(tzinfo=timezone.utc)).days
        if server_time < min_server_days:
            return False, f"🏠 You must be in this server for at least {min_server_days} days to join."
    
    return True, "Eligible"

class DatabaseManager:
    """Dedicated class for handling database operations with better error handling"""
    
    @staticmethod
    async def load_database() -> bool:
        """Load giveaway data from the database channel with enhanced error handling."""
        global giveaways, giveaway_templates, blacklisted_users, database_loaded
        
        try:
            db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
            if not db_channel:
                logging.error(f"❌ Database channel {DATABASE_CHANNEL_ID} not found!")
                # Initialize with empty data
                giveaways, giveaway_templates, blacklisted_users = {}, {}, {}
                database_loaded = True
                return False

            logging.info("🔄 Loading database from Discord channel...")
            
            # Initialize with empty data first
            giveaways = {}
            giveaway_templates = {}
            blacklisted_users = {}
            
            # Look for database messages
            messages_found = 0
            async for message in db_channel.history(limit=50, oldest_first=False):
                if message.author != bot.user:
                    continue
                    
                messages_found += 1
                
                # Check for single JSON message (new format)
                if message.content.startswith("```json") and message.content.endswith("```"):
                    try:
                        json_content = message.content[7:-3]  # Remove ```json and ```
                        data = json.loads(json_content)
                        
                        if isinstance(data, dict):
                            # New enhanced format
                            if "giveaways" in data:
                                giveaways = data.get("giveaways", {})
                                giveaway_templates = data.get("templates", {})
                                blacklisted_users = data.get("blacklisted", {})
                                logging.info(f"✅ Loaded enhanced format: {len(giveaways)} giveaways, {len(giveaway_templates)} templates")
                            else:
                                # Legacy format - just giveaways
                                giveaways = data
                                logging.info(f"✅ Loaded legacy format: {len(giveaways)} giveaways")
                            
                            database_loaded = True
                            return True
                        
                    except json.JSONDecodeError as e:
                        logging.warning(f"⚠️ JSON decode error in message {message.id}: {e}")
                        continue
                    except Exception as e:
                        logging.error(f"❌ Error processing message {message.id}: {e}")
                        continue
            
            logging.warning(f"⚠️ No valid database found in {messages_found} messages, starting fresh")
            database_loaded = True
            return True
            
        except Exception as e:
            logging.error(f"❌ Critical error loading database: {e}")
            # Initialize with empty data to prevent crashes
            giveaways, giveaway_templates, blacklisted_users = {}, {}, {}
            database_loaded = True
            return False

    @staticmethod
    async def save_database(force: bool = False) -> bool:
        """Save all data to the database channel with retry logic."""
        if not database_loaded and not force:
            logging.warning("⚠️ Database not loaded yet, skipping save")
            return False
            
        for attempt in range(MAX_RETRIES):
            try:
                db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
                if not db_channel:
                    logging.error(f"❌ Database channel {DATABASE_CHANNEL_ID} not found!")
                    return False

                # Create comprehensive data structure
                database_data = {
                    "version": DATABASE_VERSION,
                    "giveaways": giveaways,
                    "templates": giveaway_templates,
                    "blacklisted": blacklisted_users,
                    "metadata": {
                        "last_updated": datetime.now(timezone.utc).isoformat(),
                        "total_giveaways": len(giveaways),
                        "active_giveaways": sum(1 for g in giveaways.values() if g.get("status") == "active"),
                        "total_servers": len(set(g.get("server_id") for g in giveaways.values() if g.get("server_id"))),
                        "save_attempt": attempt + 1
                    }
                }
                
                json_content = json.dumps(database_data, indent=2)
                content_hash = hashlib.md5(json_content.encode()).hexdigest()[:8]
                
                # Prepare the message
                if len(json_content) > 1900:
                    # Content too large, split it
                    await DatabaseManager._save_large_database(db_channel, json_content, content_hash, database_data)
                else:
                    # Small database, send normally
                    await DatabaseManager._save_small_database(db_channel, json_content, content_hash, database_data)
                
                logging.info(f"✅ Database saved successfully (attempt {attempt + 1}, hash: {content_hash})")
                return True
                
            except discord.HTTPException as e:
                logging.error(f"❌ Discord HTTP error on attempt {attempt + 1}: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
            except Exception as e:
                logging.error(f"❌ Critical error saving database on attempt {attempt + 1}: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2)
                    continue
        
        logging.error("❌ Failed to save database after all retries")
        return False

    @staticmethod
    async def _save_small_database(channel, json_content: str, content_hash: str, metadata: dict):
        """Save small database as single message"""
        message_content = f"```json\n{json_content}\n```"
        
        embed = discord.Embed(
            title="🗄️ Giveaway Database Backup",
            description=f"**Version:** {DATABASE_VERSION}\n"
                       f"**Total Giveaways:** {metadata['metadata']['total_giveaways']}\n"
                       f"**Active:** {metadata['metadata']['active_giveaways']}\n"
                       f"**Servers:** {metadata['metadata']['total_servers']}\n"
                       f"**Templates:** {len(metadata['templates'])}\n"
                       f"**Hash:** `{content_hash}`",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        
        await channel.send(content=message_content, embed=embed)

    @staticmethod
    async def _save_large_database(channel, json_content: str, content_hash: str, metadata: dict):
        """Save large database as multiple messages"""
        chunk_size = 1900
        chunks = [json_content[i:i+chunk_size] for i in range(0, len(json_content), chunk_size)]
        
        # Send header embed first
        embed = discord.Embed(
            title="🗄️ Large Giveaway Database Backup",
            description=f"**Version:** {DATABASE_VERSION}\n"
                       f"**Total Giveaways:** {metadata['metadata']['total_giveaways']}\n"
                       f"**Active:** {metadata['metadata']['active_giveaways']}\n"
                       f"**Servers:** {metadata['metadata']['total_servers']}\n"
                       f"**Templates:** {len(metadata['templates'])}\n"
                       f"**Split into {len(chunks)} parts**\n"
                       f"**Hash:** `{content_hash}`",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        
        await channel.send(embed=embed)
        
        # Send JSON chunks
        for i, chunk in enumerate(chunks):
            chunk_message = f"**Part {i+1}/{len(chunks)}:**\n```json\n{chunk}\n```"
            await channel.send(chunk_message)

# Save queue to batch database saves
save_queue = asyncio.Queue()
save_task = None

async def queue_database_save():
    """Queue a database save to avoid too frequent saves"""
    try:
        save_queue.put_nowait(True)
    except asyncio.QueueFull:
        pass  # Queue is full, save already pending

async def database_save_worker():
    """Worker that processes database save requests"""
    while True:
        try:
            # Wait for save request
            await save_queue.get()
            
            # Wait a bit more to batch multiple requests
            await asyncio.sleep(SAVE_DELAY)
            
            # Clear any additional save requests that came in
            while not save_queue.empty():
                try:
                    save_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            
            # Perform the save
            await DatabaseManager.save_database()
            
        except Exception as e:
            logging.error(f"❌ Error in database save worker: {e}")
            await asyncio.sleep(5)  # Wait before continuing

class ConfirmationView(View):
    """A view for confirmation dialogs"""
    def __init__(self, user_id: int, timeout_seconds: int = 30):
        super().__init__(timeout=timeout_seconds)
        self.user_id = user_id
        self.confirmed = None
    
    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Only the command user can confirm this action.", ephemeral=True)
            return
        self.confirmed = True
        await interaction.response.edit_message(content="✅ Confirmed!", view=None)
        self.stop()
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Only the command user can cancel this action.", ephemeral=True)
            return
        self.confirmed = False
        await interaction.response.edit_message(content="❌ Cancelled!", view=None)
        self.stop()

class JoinView(View):
    """Enhanced view for joining giveaways with better error handling."""
    def __init__(self, message_id: str):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="🎉 Join Giveaway", style=discord.ButtonStyle.green, custom_id="join_button")
    async def join(self, interaction: discord.Interaction, button: Button):
        """Enhanced join callback with comprehensive checks."""
        await interaction.response.defer(ephemeral=True)
        
        user_id = str(interaction.user.id)
        giveaway_data = giveaways.get(self.message_id)

        if not giveaway_data:
            await interaction.followup.send("❌ This giveaway no longer exists.", ephemeral=True)
            return

        if giveaway_data.get("status") != "active":
            status = giveaway_data.get("status", "unknown")
            await interaction.followup.send(f"❌ This giveaway is {status}.", ephemeral=True)
            return

        # Verify server
        if giveaway_data.get("server_id") != interaction.guild.id:
            await interaction.followup.send("❌ This giveaway is not for this server.", ephemeral=True)
            return

        # Check if already joined
        if "participants" not in giveaway_data:
            giveaway_data["participants"] = []

        if user_id in giveaway_data["participants"]:
            await interaction.followup.send("❌ You have already joined this giveaway!", ephemeral=True)
            return

        # Check user eligibility
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if not member:
            await interaction.followup.send("❌ Cannot verify eligibility outside of a guild.", ephemeral=True)
            return
        
        eligible, reason = await check_user_eligibility(member, giveaway_data)
        if not eligible:
            await interaction.followup.send(reason, ephemeral=True)
            return

        # Add user to giveaway
        giveaway_data["participants"].append(user_id)
        giveaway_data["last_participant_join"] = datetime.now(timezone.utc).isoformat()
        giveaways[self.message_id] = giveaway_data
        
        # Queue database save
        await queue_database_save()
        
        await interaction.followup.send("✅ You have successfully joined the giveaway! Good luck! 🍀", ephemeral=True)

        # Update participant count in embed
        try:
            original_message = interaction.message
            if original_message.embeds:
                updated_embed = original_message.embeds[0].copy()
                description = updated_embed.description
                
                lines = description.split('\n')
                for i, line in enumerate(lines):
                    if line.startswith("👥 **Participants:**"):
                        lines[i] = f"👥 **Participants:** {len(giveaway_data['participants'])}"
                        break
                
                updated_embed.description = '\n'.join(lines)
                await original_message.edit(embed=updated_embed)
        except Exception as e:
            logging.warning(f"Could not update embed for giveaway {self.message_id}: {e}")

# Enhanced slash commands

@tree.command(name="giveaway", description="Start a giveaway with advanced options")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    prize="What is the prize?",
    winners="How many winners?",
    duration="Duration (1m, 1h, 1d)",
    donor="The name of the giveaway donor (optional)",
    role="Optional role required to join",
    min_account_age="Minimum account age in days (optional)",
    min_server_time="Minimum time in server in days (optional)"
)
async def giveaway(
    interaction: discord.Interaction,
    prize: str,
    winners: int,
    duration: str,
    donor: Optional[str] = None,
    role: Optional[discord.Role] = None,
    min_account_age: Optional[int] = None,
    min_server_time: Optional[int] = None
):
    """Start a new giveaway with enhanced validation and features."""
    await interaction.response.defer()
    
    # Ensure database is loaded
    if not database_loaded:
        await interaction.followup.send("❌ Database is still loading. Please try again in a moment.", ephemeral=True)
        return
    
    # Comprehensive input validation
    if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
        await interaction.followup.send("❌ Giveaways can only be started in text channels!", ephemeral=True)
        return

    if interaction.guild is None:
        await interaction.followup.send("❌ This command can only be used in a server!", ephemeral=True)
        return

    if winners <= 0 or winners > 100:
        await interaction.followup.send("❌ Number of winners must be between 1 and 100.", ephemeral=True)
        return

    if len(prize) > 256:
        await interaction.followup.send("❌ Prize description is too long (max 256 characters).", ephemeral=True)
        return

    # Parse duration with better error handling
    total_seconds = 0
    duration_lower = duration.lower().strip()
    
    # Support multiple formats
    pattern = r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?'
    match = re.fullmatch(pattern, duration_lower)
    
    if match and any(match.groups()):
        days, hours, minutes, seconds = match.groups()
        total_seconds = (
            (int(days or 0) * 86400) +
            (int(hours or 0) * 3600) +
            (int(minutes or 0) * 60) +
            (int(seconds or 0))
        )
    else:
        # Fallback to simple format
        simple_match = re.fullmatch(r'(\d+)([smhd])', duration_lower)
        if simple_match:
            value = int(simple_match.group(1))
            unit = simple_match.group(2)
            multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
            total_seconds = value * multipliers[unit]

    if total_seconds <= 0:
        await interaction.followup.send(
            "❌ Invalid duration format. Examples: `30m`, `2h`, `1d`, `1d2h30m`",
            ephemeral=True
        )
        return

    if total_seconds < 60:
        await interaction.followup.send("❌ Giveaway duration must be at least 1 minute.", ephemeral=True)
        return

    if total_seconds > 2592000:  # 30 days
        await interaction.followup.send("❌ Giveaway duration cannot exceed 30 days.", ephemeral=True)
        return

    # Calculate end time
    end_time = datetime.now(timezone.utc) + timedelta(seconds=total_seconds)
    end_timestamp = int(end_time.timestamp())

    # Set default donor
    donor_name = donor or interaction.user.display_name

    # Build description
    description_parts = [
        f"🎁 **Prize:** {prize}",
        f"✨ **Donor:** {donor_name}",
        f"⏰ **Ends:** <t:{end_timestamp}:R> (<t:{end_timestamp}:f>)",
        f"🏆 **Winners:** {winners}",
        f"👥 **Participants:** 0"
    ]

    if role:
        description_parts.append(f"🛡️ **Required Role:** {role.mention}")
    
    if min_account_age:
        description_parts.append(f"⏰ **Min Account Age:** {min_account_age} days")
    
    if min_server_time:
        description_parts.append(f"🏠 **Min Server Time:** {min_server_time} days")

    embed = discord.Embed(
        title="🎉✨ GIVEAWAY! ✨🎉",
        description="\n".join(description_parts),
        color=discord.Color.from_rgb(255, 105, 180),
        timestamp=end_time
    )
    embed.set_footer(text=f"Started by {interaction.user.display_name} • Ends")
    
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    view = JoinView(message_id="temp_placeholder")

    await interaction.followup.send(embed=embed, view=view)
    message = await interaction.original_response()

    # Register view and save giveaway data
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
        "donor_name": donor_name,
        "required_role": role.id if role else None,
        "min_account_age_days": min_account_age or 0,
        "min_server_days": min_server_time or 0,
        "status": "active",
        "created_by": interaction.user.id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "end_time": end_time.isoformat(),
        "duration": duration,
        "original_duration_seconds": total_seconds
    }
    
    # Queue database save
    await queue_database_save()
    logging.info(f"🎉 Giveaway {message_id_str} created in {interaction.guild.name} ({interaction.guild.id}) - ends in {duration}")

@tree.command(name="endgiveaway", description="End a giveaway and pick winners")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(message_id="The message ID of the giveaway to end")
async def end_giveaway(interaction: discord.Interaction, message_id: str):
    """End a giveaway with confirmation and enhanced winner selection."""
    await interaction.response.defer(ephemeral=True)

    # Validate message ID
    if not await validate_message_id(message_id):
        await interaction.followup.send("❌ Please provide a valid Discord message ID.", ephemeral=True)
        return

    giveaway_data = giveaways.get(message_id)
    if not giveaway_data:
        await interaction.followup.send("❌ Giveaway not found.", ephemeral=True)
        return

    if giveaway_data.get("status") != "active":
        await interaction.followup.send(f"❌ This giveaway is already {giveaway_data.get('status', 'inactive')}.", ephemeral=True)
        return

    # Enhanced permission check
    is_creator = giveaway_data.get("created_by") == interaction.user.id
    has_manage_perms = interaction.user.guild_permissions.manage_guild
    
    if not (is_creator or has_manage_perms):
        await interaction.followup.send("❌ Only the giveaway creator or users with Manage Server permission can end this giveaway.", ephemeral=True)
        return

    # Verify server
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
        await queue_database_save()
        return

    # Pick winners
    winners_count = min(len(participants), giveaway_data["winners"])
    winner_ids = random.sample(participants, winners_count)
    winner_mentions = [f"<@{winner_id}>" for winner_id in winner_ids]

    # Update giveaway status
    giveaway_data["status"] = "ended"
    giveaway_data["ended_at"] = datetime.now(timezone.utc).isoformat()
    giveaway_data["ended_by"] = interaction.user.id
    giveaway_data["winner_ids"] = winner_ids
    giveaways[message_id] = giveaway_data
    await queue_database_save()

    # Update original message
    channel = bot.get_channel(giveaway_data["channel_id"])
    if channel and isinstance(channel, (discord.TextChannel, discord.Thread)):
        try:
            original_message = await channel.fetch_message(int(message_id))
            
            ended_embed = discord.Embed(
                title="🎉 GIVEAWAY ENDED! 🎉",
                description=f"🎁 **Prize:** {giveaway_data['prize']}\n"
                           f"✨ **Donor:** {giveaway_data['donor_name']}\n"
                           f"🏆 **Winners:** {' '.join(winner_mentions)}\n"
                           f"👥 **Total Participants:** {len(participants)}\n"
                           f"⏰ **Ended by:** {interaction.user.mention}",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )
            ended_embed.set_footer(text="Giveaway ended")
            await original_message.edit(embed=ended_embed, view=None)
            
            # Winner announcement
            winner_announcement = (
                f"🎉 **GIVEAWAY ENDED!** 🎉\n\n"
                f"🎁 **Prize:** {giveaway_data['prize']}\n"
                f"🏆 **{'Winner' if len(winner_mentions) == 1 else 'Winners'}:** {' '.join(winner_mentions)}\n\n"
                f"Congratulations! Please contact the giveaway host to claim your prize!"
            )
            
            await original_message.reply(winner_announcement)
            
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            logging.warning(f"Could not update original giveaway message {message_id}: {e}")

    await interaction.followup.send(
        f"✅ Giveaway ended successfully!\n🏆 Winners: {' '.join(winner_mentions)}", 
        ephemeral=True
    )
    
    logging.info(f"Giveaway {message_id} ended in {interaction.guild.name} with {len(winner_ids)} winners")

@tree.command(name="giveawaystats", description="View comprehensive giveaway statistics")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_stats(interaction: discord.Interaction):
    """Show enhanced giveaway statistics for the current server."""
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server!", ephemeral=True)
        return

    if not database_loaded:
        await interaction.response.send_message("❌ Database is still loading. Please try again in a moment.", ephemeral=True)
        return

    server_giveaways = {k: v for k, v in giveaways.items() if v.get("server_id") == interaction.guild.id}
    server_id = str(interaction.guild.id)
    
    # Calculate statistics
    total = len(server_giveaways)
    active = sum(1 for g in server_giveaways.values() if g.get("status") == "active")
    ended = sum(1 for g in server_giveaways.values() if g.get("status") == "ended")
    cancelled = sum(1 for g in server_giveaways.values() if g.get("status") == "cancelled")
    
    # Calculate participation statistics
    total_participants = sum(len(g.get("participants", [])) for g in server_giveaways.values())
    total_winners = sum(len(g.get("winner_ids", [])) for g in server_giveaways.values())
    
    embed = discord.Embed(
        title=f"📊 Giveaway Statistics - {interaction.guild.name}",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc)
    )
    
    # Main statistics
    embed.add_field(name="🎉 Total Giveaways", value=str(total), inline=True)
    embed.add_field(name="✅ Active", value=str(active), inline=True)
    embed.add_field(name="🏆 Completed", value=str(ended), inline=True)
    embed.add_field(name="🚫 Cancelled", value=str(cancelled), inline=True)
    embed.add_field(name="👥 Total Participants", value=str(total_participants), inline=True)
    embed.add_field(name="🎁 Total Winners", value=str(total_winners), inline=True)
    
    # Templates and blacklist info
    template_count = len(giveaway_templates.get(server_id, {}))
    blacklist_count = len(blacklisted_users.get(server_id, {}))
    embed.add_field(name="📋 Templates", value=str(template_count), inline=True)
    embed.add_field(name="🚫 Blacklisted Users", value=str(blacklist_count), inline=True)
    
    # Average participation
    avg_participation = round(total_participants / total, 1) if total > 0 else 0
    embed.add_field(name="📈 Avg Participants", value=str(avg_participation), inline=True)

    # Recent activity
    recent_giveaways = sorted(
        [(k, v) for k, v in server_giveaways.items()],
        key=lambda x: x[1].get("created_at", ""),
        reverse=True
    )[:5]

    if recent_giveaways:
        recent_text = ""
        for msg_id, data in recent_giveaways:
            status_emoji = {"active": "🟢", "ended": "🔴", "cancelled": "⚫"}.get(data.get("status"), "❓")
            participant_count = len(data.get("participants", []))
            prize_short = data['prize'][:30] + ('...' if len(data['prize']) > 30 else '')
            recent_text += f"{status_emoji} **{prize_short}** ({participant_count} participants)\n"
        
        embed.add_field(name="🕒 Recent Giveaways", value=recent_text, inline=False)

    embed.set_footer(text=f"Database loaded • {len(giveaways)} total giveaways across all servers")
    
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="force_reload", description="Force reload the database (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def force_reload_database(interaction: discord.Interaction):
    """Force reload the database from the Discord channel."""
    await interaction.response.defer(ephemeral=True)
    
    logging.info(f"🔄 Force reload requested by {interaction.user} in {interaction.guild.name}")
    
    global database_loaded
    database_loaded = False
    
    success = await DatabaseManager.load_database()
    
    if success:
        embed = discord.Embed(
            title="✅ Database Reloaded Successfully",
            description=f"**Giveaways Loaded:** {len(giveaways)}\n"
                       f"**Templates Loaded:** {len(giveaway_templates)}\n"
                       f"**Blacklisted Users:** {sum(len(bl) for bl in blacklisted_users.values())}\n"
                       f"**Active Giveaways:** {sum(1 for g in giveaways.values() if g.get('status') == 'active')}",
            color=discord.Color.green()
        )
    else:
        embed = discord.Embed(
            title="⚠️ Database Reload Issues",
            description="Database was reloaded but some issues were encountered. Check logs for details.",
            color=discord.Color.orange()
        )
    
    await interaction.followup.send(embed=embed, ephemeral=True)
    
    # Re-attach views for active giveaways
    active_count = 0
    for message_id, data in giveaways.items():
        if data.get("status") == "active":
            try:
                bot.add_view(JoinView(message_id=message_id), message_id=int(message_id))
                active_count += 1
            except Exception as e:
                logging.warning(f"Could not re-attach view for giveaway {message_id}: {e}")
    
    logging.info(f"🎉 Re-attached {active_count} active giveaway views after reload")

@tree.command(name="database_status", description="Check database connection and status")
@app_commands.checks.has_permissions(manage_guild=True)
async def database_status(interaction: discord.Interaction):
    """Show database status and connection info."""
    await interaction.response.defer(ephemeral=True)
    
    # Test database channel access
    db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
    channel_status = "✅ Connected" if db_channel else "❌ Not Found"
    
    # Check permissions
    can_read = can_send = False
    if db_channel:
        permissions = db_channel.permissions_for(db_channel.guild.me)
        can_read = permissions.read_message_history
        can_send = permissions.send_messages
    
    embed = discord.Embed(
        title="🗄️ Database Status",
        color=discord.Color.green() if database_loaded else discord.Color.red()
    )
    
    embed.add_field(name="📊 Database Loaded", value="✅ Yes" if database_loaded else "❌ No", inline=True)
    embed.add_field(name="🔗 Channel Status", value=channel_status, inline=True)
    embed.add_field(name="📖 Can Read History", value="✅ Yes" if can_read else "❌ No", inline=True)
    embed.add_field(name="📝 Can Send Messages", value="✅ Yes" if can_send else "❌ No", inline=True)
    
    embed.add_field(name="🎉 Total Giveaways", value=str(len(giveaways)), inline=True)
    embed.add_field(name="✅ Active Giveaways", value=str(sum(1 for g in giveaways.values() if g.get("status") == "active")), inline=True)
    
    # Server specific stats
    server_giveaways = {k: v for k, v in giveaways.items() if v.get("server_id") == interaction.guild.id}
    server_active = sum(1 for g in server_giveaways.values() if g.get("status") == "active")
    
    embed.add_field(name="🏠 Server Giveaways", value=str(len(server_giveaways)), inline=True)
    embed.add_field(name="🟢 Server Active", value=str(server_active), inline=True)
    
    if db_channel:
        embed.add_field(name="🆔 Database Channel", value=f"<#{DATABASE_CHANNEL_ID}>", inline=True)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# Enhanced event handlers and background tasks

@bot.event
async def on_ready():
    """Enhanced startup sequence with better database loading."""
    logging.info(f"🚀 Enhanced Giveaway Bot logged in as {bot.user}")
    
    # Start the database save worker
    global save_task
    if save_task is None or save_task.done():
        save_task = asyncio.create_task(database_save_worker())
        logging.info("🔧 Database save worker started")
    
    # Load all data from database with retries
    max_load_attempts = 3
    for attempt in range(max_load_attempts):
        try:
            logging.info(f"🔄 Loading database (attempt {attempt + 1}/{max_load_attempts})...")
            success = await DatabaseManager.load_database()
            if success:
                break
            elif attempt < max_load_attempts - 1:
                logging.warning(f"⚠️ Database load attempt {attempt + 1} failed, retrying in 5 seconds...")
                await asyncio.sleep(5)
        except Exception as e:
            logging.error(f"❌ Database load attempt {attempt + 1} failed with error: {e}")
            if attempt < max_load_attempts - 1:
                await asyncio.sleep(5)
    
    # Sync commands
    try:
        synced = await tree.sync()
        logging.info(f"✅ Synced {len(synced)} slash commands.")
    except Exception as e:
        logging.error(f"❌ Failed to sync commands: {e}")

    # Re-attach views for active giveaways
    active_count = 0
    failed_count = 0
    for message_id, data in giveaways.items():
        if data.get("status") == "active":
            try:
                bot.add_view(JoinView(message_id=message_id), message_id=int(message_id))
                active_count += 1
            except Exception as e:
                failed_count += 1
                logging.warning(f"Could not re-attach view for giveaway {message_id}: {e}")
    
    logging.info(f"🎉 Re-attached {active_count} active giveaway views ({failed_count} failed)")
    logging.info(f"📊 Managing {len(giveaways)} total giveaways across {len(set(g.get('server_id') for g in giveaways.values() if g.get('server_id')))} servers")
    logging.info(f"📋 {sum(len(templates) for templates in giveaway_templates.values())} templates available")
    logging.info(f"🚫 {sum(len(bl) for bl in blacklisted_users.values())} blacklisted users total")
    
    # Start background tasks
    if not check_giveaways.is_running():
        check_giveaways.start()
        logging.info("⏰ Giveaway checker task started")
    
    if not database_maintenance.is_running():
        database_maintenance.start()
        logging.info("🔧 Database maintenance task started")
    
    logging.info("🎊 Enhanced Giveaway Bot is fully ready!")

@tasks.loop(minutes=1)
async def check_giveaways():
    """Enhanced giveaway expiration checker with better error handling."""
    if not database_loaded:
        return
        
    now = datetime.now(timezone.utc)
    expired_giveaways = []
    
    for message_id, data in list(giveaways.items()):
        if data.get("status") != "active":
            continue
            
        if "end_time" not in data:
            logging.warning(f"Giveaway {message_id} missing end_time, skipping")
            continue
            
        try:
            end_time = datetime.fromisoformat(data["end_time"].replace('Z', '+00:00'))
        except (ValueError, AttributeError) as e:
            logging.error(f"Invalid end_time format for giveaway {message_id}: {e}")
            continue
        
        # Check if giveaway has expired
        if now >= end_time:
            expired_giveaways.append((message_id, data))
    
    # Process expired giveaways
    if expired_giveaways:
        logging.info(f"⏰ Processing {len(expired_giveaways)} expired giveaways")
        for message_id, data in expired_giveaways:
            await process_expired_giveaway(message_id, data)

async def process_expired_giveaway(message_id: str, data: dict):
    """Process a single expired giveaway with comprehensive error handling."""
    try:
        participants = data.get("participants", [])
        
        # Get the channel and verify it exists
        channel = bot.get_channel(data["channel_id"])
        if not channel:
            logging.warning(f"Channel {data['channel_id']} not found for giveaway {message_id}")
            data["status"] = "ended"
            data["ended_at"] = datetime.now(timezone.utc).isoformat()
            data["ended_by"] = "automatic_channel_missing"
            giveaways[message_id] = data
            await queue_database_save()
            return
        
        # Try to fetch the original message
        try:
            message = await channel.fetch_message(int(message_id))
        except discord.NotFound:
            logging.warning(f"Message {message_id} not found, marking giveaway as ended")
            data["status"] = "ended"
            data["ended_at"] = datetime.now(timezone.utc).isoformat()
            data["ended_by"] = "automatic_message_deleted"
            giveaways[message_id] = data
            await queue_database_save()
            return
        except discord.Forbidden:
            logging.warning(f"No permission to access message {message_id}")
            data["status"] = "ended"
            data["ended_at"] = datetime.now(timezone.utc).isoformat()
            data["ended_by"] = "automatic_no_permission"
            giveaways[message_id] = data
            await queue_database_save()
            return
        
        # Update giveaway status
        data["status"] = "ended"
        data["ended_at"] = datetime.now(timezone.utc).isoformat()
        data["ended_by"] = "automatic"
        
        if not participants:
            # No participants case
            ended_embed = discord.Embed(
                title="🎉 GIVEAWAY ENDED! 🎉",
                description=f"🎁 **Prize:** {data['prize']}\n"
                           f"✨ **Donor:** {data['donor_name']}\n"
                           f"❌ **Result:** No one joined this giveaway",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            ended_embed.set_footer(text="Giveaway ended automatically")
            
            await message.edit(embed=ended_embed, view=None)
            await message.reply("😔 This giveaway ended with no participants. Better luck next time!")
            
        else:
            # Pick winners
            winners_count = min(len(participants), data["winners"])
            winner_ids = random.sample(participants, winners_count)
            winner_mentions = [f"<@{uid}>" for uid in winner_ids]
            
            data["winner_ids"] = winner_ids
            
            # Update message with results
            ended_embed = discord.Embed(
                title="🎉 GIVEAWAY ENDED! 🎉",
                description=f"🎁 **Prize:** {data['prize']}\n"
                           f"✨ **Donor:** {data['donor_name']}\n"
                           f"🏆 **{'Winner' if len(winner_mentions) == 1 else 'Winners'}:** {' '.join(winner_mentions)}\n"
                           f"👥 **Total Participants:** {len(participants)}",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )
            ended_embed.set_footer(text="Giveaway ended automatically")
            
            await message.edit(embed=ended_embed, view=None)
            
            # Enhanced winner announcement
            winner_announcement = (
                f"🎊 **GIVEAWAY RESULTS ARE IN!** 🎊\n\n"
                f"🎁 **Prize:** {data['prize']}\n"
                f"🏆 **{'Winner' if len(winner_mentions) == 1 else 'Winners'}:** {' '.join(winner_mentions)}\n\n"
                f"🎉 Congratulations! Please contact {data['donor_name']} or a server admin to claim your prize!\n"
                f"📩 Make sure your DMs are open so we can contact you!"
            )
            
            await message.reply(winner_announcement)
        
        # Save updated data
        giveaways[message_id] = data
        await queue_database_save()
        
        server_name = data.get('server_name', 'Unknown Server')
        winner_count = len(data.get("winner_ids", [])) if participants else 0
        logging.info(f"🎉 Auto-ended giveaway {message_id} in {server_name} - {winner_count} winners")
        
    except Exception as e:
        logging.error(f"Error processing expired giveaway {message_id}: {e}")
        # Mark as ended to prevent retry loops
        try:
            data["status"] = "ended"
            data["ended_at"] = datetime.now(timezone.utc).isoformat()
            data["ended_by"] = f"automatic_error_{type(e).__name__}"
            data["error"] = str(e)
            giveaways[message_id] = data
            await queue_database_save()
        except:
            pass  # Prevent cascade failures

@tasks.loop(hours=24)
async def database_maintenance():
    """Perform daily database maintenance and cleanup."""
    if not database_loaded:
        return
        
    try:
        logging.info("🔧 Starting daily database maintenance...")
        
        # Clean up old ended/cancelled giveaways (older than 90 days)
        cleanup_date = datetime.now(timezone.utc) - timedelta(days=90)
        cleaned_count = 0
        
        for message_id in list(giveaways.keys()):
            data = giveaways[message_id]
            if data.get("status") in ["ended", "cancelled"]:
                try:
                    end_date_str = data.get("ended_at") or data.get("cancelled_at")
                    if end_date_str:
                        end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                        if end_date < cleanup_date:
                            del giveaways[message_id]
                            cleaned_count += 1
                except (ValueError, AttributeError):
                    continue
        
        # Save cleaned database
        if cleaned_count > 0:
            await DatabaseManager.save_database(force=True)
            logging.info(f"🧹 Maintenance complete: {cleaned_count} old giveaways cleaned")
        else:
            logging.info("✨ Database maintenance complete - no cleanup needed")
            
        # Log current statistics
        active_count = sum(1 for g in giveaways.values() if g.get("status") == "active")
        total_servers = len(set(g.get("server_id") for g in giveaways.values() if g.get("server_id")))
        
        logging.info(f"📊 Current stats: {len(giveaways)} giveaways ({active_count} active) across {total_servers} servers")
        
    except Exception as e:
        logging.error(f"❌ Error during database maintenance: {e}")

@bot.event
async def on_guild_join(guild):
    """Enhanced guild join handler."""
    logging.info(f"🆕 Joined new server: {guild.name} ({guild.id}) with {guild.member_count} members")

@bot.event
async def on_guild_remove(guild):
    """Enhanced guild leave handler."""
    logging.info(f"👋 Left server: {guild.name} ({guild.id})")
    server_giveaways = sum(1 for g in giveaways.values() if g.get("server_id") == guild.id)
    if server_giveaways > 0:
        logging.info(f"📊 Had {server_giveaways} giveaways in {guild.name}")

@bot.event
async def on_application_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Enhanced error handling for slash commands."""
    if isinstance(error, app_commands.MissingPermissions):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ You need 'Manage Server' permission to use giveaway commands.",
                ephemeral=True
            )
        return
    
    # Log unexpected errors
    logging.error(f"Slash command error in {interaction.guild}: {error}")
    
    if not interaction.response.is_done():
        await interaction.response.send_message(
            "❌ An unexpected error occurred. Please try again later.",
            ephemeral=True
        )

# Get Discord token and start the bot
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("❌ DISCORD_TOKEN is not set in the environment.")

# Start keep alive system and run the bot
logging.info("🚀 Starting Enhanced Giveaway Bot...")
keep_alive()
bot.run(DISCORD_TOKEN)
