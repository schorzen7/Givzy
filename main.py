import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput
import json
import random
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import re
import logging
import asyncio
import hashlib
from keep_alive import keep_alive
from subs import (
    add_subscription_commands, 
    load_subscriptions, 
    save_subscriptions, 
    check_feature_access, 
    get_server_tier,
    SubscriptionTier
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Database channel ID
DATABASE_CHANNEL_ID = 1393415294663528529

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Global data structures - server-isolated
giveaways = {}
pending_database_save = False
last_database_save = datetime.now()

def get_server_giveaways(server_id: int) -> Dict:
    """Get giveaways for a specific server only"""
    return {k: v for k, v in giveaways.items() if v.get("server_id") == server_id}

async def validate_message_id(message_id: str) -> bool:
    """Validate that message_id is a valid Discord message ID"""
    try:
        # Discord message IDs are 64-bit integers
        mid = int(message_id)
        return 17 <= len(str(mid)) <= 20  # Discord IDs are typically 17-20 digits
    except ValueError:
        return False

async def validate_server_access(interaction: discord.Interaction, giveaway_data: dict) -> bool:
    """Validate that user can only access giveaways from their current server"""
    if not interaction.guild:
        return False
    return giveaway_data.get("server_id") == interaction.guild.id

async def check_user_eligibility(user: discord.Member, giveaway_data: dict) -> tuple[bool, str]:
    """Check if user meets all requirements to join giveaway"""
    now = datetime.now(timezone.utc)
    
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

async def batch_save_database():
    """Batch database saves to avoid rate limiting"""
    global pending_database_save, last_database_save
    
    if not pending_database_save:
        pending_database_save = True
        # Wait 5 seconds to batch multiple changes
        await asyncio.sleep(5)
        
        # Only save if it's been at least 30 seconds since last save
        if (datetime.now() - last_database_save).total_seconds() >= 30:
            await save_database()
            last_database_save = datetime.now()
        
        pending_database_save = False

async def load_database():
    """Load giveaway data from the database channel with improved error handling and recovery."""
    global giveaways
    
    try:
        db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
        if not db_channel:
            logging.error(f"Database channel {DATABASE_CHANNEL_ID} not found!")
            # Initialize with empty data to prevent crashes
            giveaways = {}
            return

        # Initialize with empty data
        giveaways = {}
        
        # Look for the most recent valid database message
        messages_to_check = []
        
        # Collect recent messages from the database channel
        async for message in db_channel.history(limit=50):  # Increased limit for better recovery
            if message.author == bot.user:
                messages_to_check.append(message)
        
        # Sort messages by creation time (newest first)
        messages_to_check.sort(key=lambda m: m.created_at, reverse=True)
        
        # Try to find complete database backup first
        for message in messages_to_check:
            if not message.content:
                continue
                
            # Check for single complete JSON message
            if message.content.startswith("```json") and message.content.endswith("```"):
                try:
                    json_content = message.content[7:-3].strip()  # Remove ```json and ```
                    if not json_content:
                        continue
                        
                    data = json.loads(json_content)
                    
                    # Validate the data structure
                    if isinstance(data, dict):
                        # New format with separate sections
                        if "giveaways" in data:
                            loaded_giveaways = data.get("giveaways", {})
                            
                            # Validate that loaded data is properly structured
                            if isinstance(loaded_giveaways, dict):
                                giveaways = loaded_giveaways
                                
                                logging.info(f"✅ Successfully loaded database from single message:")
                                logging.info(f"   📊 {len(giveaways)} giveaways")
                                
                                # Log active giveaways for verification
                                active_count = sum(1 for g in giveaways.values() if g.get("status") == "active")
                                logging.info(f"   🎉 {active_count} active giveaways found")
                                
                                if active_count > 0:
                                    logging.info("   Active giveaway details:")
                                    for msg_id, data in giveaways.items():
                                        if data.get("status") == "active":
                                            server_name = data.get("server_name", "Unknown")
                                            prize = data.get("prize", "Unknown Prize")
                                            participants = len(data.get("participants", []))
                                            logging.info(f"     - {msg_id}: {prize} in {server_name} ({participants} participants)")
                                
                                return
                        else:
                            # Legacy format - just giveaways
                            if all(isinstance(v, dict) for v in data.values()):
                                giveaways = data
                                logging.info(f"✅ Loaded legacy database format: {len(giveaways)} giveaways")
                                return
                    
                except json.JSONDecodeError as e:
                    logging.warning(f"JSON decode error in message {message.id}: {e}")
                    continue
                except Exception as e:
                    logging.warning(f"Error processing message {message.id}: {e}")
                    continue
        
        # Try to reconstruct from multi-part messages if single message failed
        logging.info("🔍 Attempting multi-part database reconstruction...")
        
        part_messages = []
        
        for message in messages_to_check:
            if "Part" in message.content and "```json" in message.content:
                try:
                    # Extract part number and content
                    part_match = re.search(r'Part (\d+)/(\d+)', message.content)
                    if part_match:
                        part_num = int(part_match.group(1))
                        total_parts = int(part_match.group(2))
                        
                        start = message.content.find("```json") + 7
                        end = message.content.rfind("```")
                        if start > 6 and end > start:
                            json_content = message.content[start:end]
                            part_messages.append((part_num, json_content, message.created_at))
                except Exception as e:
                    logging.warning(f"Error parsing multi-part message {message.id}: {e}")
                    continue
        
        # Sort parts by part number and reconstruct
        if part_messages:
            part_messages.sort(key=lambda x: x[0])  # Sort by part number
            combined_json = "".join([content for _, content, _ in part_messages])
            
            try:
                data = json.loads(combined_json)
                
                if isinstance(data, dict):
                    if "giveaways" in data:
                        giveaways = data.get("giveaways", {})
                    else:
                        giveaways = data
                    
                    logging.info(f"✅ Reconstructed database from {len(part_messages)} parts:")
                    logging.info(f"   📊 {len(giveaways)} giveaways")
                    
                    active_count = sum(1 for g in giveaways.values() if g.get("status") == "active")
                    logging.info(f"   🎉 {active_count} active giveaways found")
                    return
                    
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse reconstructed multi-part JSON: {e}")
            except Exception as e:
                logging.error(f"Error processing reconstructed data: {e}")
        
        # If all attempts failed, start with empty database
        logging.warning("⚠️ No valid database found, starting with empty database")
        giveaways = {}
        
    except Exception as e:
        logging.error(f"Critical error loading database: {e}")
        # Initialize with empty data to prevent crashes
        giveaways = {}

async def save_database():
    """Save all data to the database channel with improved structure."""
    try:
        db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
        if not db_channel:
            logging.error(f"Database channel {DATABASE_CHANNEL_ID} not found!")
            return

        # Create comprehensive data structure
        database_data = {
            "giveaways": giveaways,
            "metadata": {
                "version": "2.2-givzy",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "total_giveaways": len(giveaways),
                "active_giveaways": sum(1 for g in giveaways.values() if g.get("status") == "active"),
                "total_servers": len(set(g.get("server_id") for g in giveaways.values() if g.get("server_id"))),
                "save_timestamp": datetime.now(timezone.utc).timestamp()
            }
        }
        
        json_content = json.dumps(database_data, indent=2, ensure_ascii=False)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Calculate content hash for integrity
        content_hash = hashlib.md5(json_content.encode()).hexdigest()[:8]
        
        # Check if content is too large for Discord
        if len(json_content) > 1900:
            # Split into chunks
            chunk_size = 1900
            chunks = [json_content[i:i+chunk_size] for i in range(0, len(json_content), chunk_size)]
            
            # Send header embed first
            embed = discord.Embed(
                title="🗄️ Givzy Giveaway Database Backup",
                description=f"**Database Version:** 2.2-givzy (Multi-Server)\n"
                           f"**Total Giveaways:** {database_data['metadata']['total_giveaways']}\n"
                           f"**Active:** {database_data['metadata']['active_giveaways']}\n"
                           f"**Servers:** {database_data['metadata']['total_servers']}\n"
                           f"**Last Updated:** {timestamp}\n"
                           f"**Split into {len(chunks)} parts**\n"
                           f"**Hash:** `{content_hash}`",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            
            await db_channel.send(embed=embed)
            
            # Send JSON chunks with clear part indicators
            for i, chunk in enumerate(chunks):
                chunk_message = f"**Part {i+1}/{len(chunks)}:**\n```json\n{chunk}\n```"
                await db_channel.send(chunk_message)
                # Add small delay to ensure proper order
                await asyncio.sleep(0.5)
            
            logging.info(f"✅ Database saved in {len(chunks)} parts (hash: {content_hash})")
        else:
            # Small database - single message
            message_content = f"```json\n{json_content}\n```"
            embed = discord.Embed(
                title="🗄️ Givzy Giveaway Database Backup",
                description=f"**Database Version:** 2.2-givzy (Multi-Server)\n"
                           f"**Total Giveaways:** {database_data['metadata']['total_giveaways']}\n"
                           f"**Active:** {database_data['metadata']['active_giveaways']}\n"
                           f"**Servers:** {database_data['metadata']['total_servers']}\n"
                           f"**Last Updated:** {timestamp}\n"
                           f"**Hash:** `{content_hash}`",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            
            await db_channel.send(content=message_content, embed=embed)
            logging.info(f"✅ Database saved successfully (hash: {content_hash})")
        
        # Log active giveaways for verification
        active_giveaways = [g for g in giveaways.values() if g.get("status") == "active"]
        if active_giveaways:
            logging.info(f"📝 Saved {len(active_giveaways)} active giveaways:")
            for g in active_giveaways[:3]:  # Log first 3 for brevity
                server_name = g.get("server_name", "Unknown")
                prize = g.get("prize", "Unknown Prize")
                participants = len(g.get("participants", []))
                logging.info(f"   - {prize} in {server_name} ({participants} participants)")
            if len(active_giveaways) > 3:
                logging.info(f"   ... and {len(active_giveaways) - 3} more")
        
    except discord.HTTPException as e:
        logging.error(f"Discord HTTP error saving database: {e}")
    except Exception as e:
        logging.error(f"Critical error saving database: {e}")

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
        self.stop()
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Only the command user can cancel this action.", ephemeral=True)
            return
        self.confirmed = False
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

        # SECURITY: Validate server access
        if not await validate_server_access(interaction, giveaway_data):
            await interaction.followup.send("❌ This giveaway is not accessible from this server.", ephemeral=True)
            return

        if giveaway_data.get("status") != "active":
            status = giveaway_data.get("status", "unknown")
            await interaction.followup.send(f"❌ This giveaway is {status}.", ephemeral=True)
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
        
        # Batch save to avoid rate limiting
        asyncio.create_task(batch_save_database())
        
        await interaction.followup.send("✅ You have successfully joined the giveaway! Good luck! 🍀", ephemeral=True)

        # Update participant count in embed - with permission check
        try:
            original_message = interaction.message
            if original_message and original_message.embeds:
                # Check if we have permission to edit messages
                if interaction.guild.me.guild_permissions.manage_messages:
                    updated_embed = original_message.embeds[0].copy()
                    description = updated_embed.description
                    
                    lines = description.split('\n')
                    for i, line in enumerate(lines):
                        if line.startswith("👥 **Participants:**"):
                            lines[i] = f"👥 **Participants:** {len(giveaway_data['participants'])}"
                            break
                    
                    updated_embed.description = '\n'.join(lines)
                    await original_message.edit(embed=updated_embed)
                else:
                    logging.warning(f"Missing permission to edit message for giveaway {self.message_id}")
        except discord.Forbidden:
            logging.warning(f"Permission denied when trying to update embed for giveaway {self.message_id}")
        except Exception as e:
            logging.warning(f"Could not update embed for giveaway {self.message_id}: {e}")

# Enhanced slash commands with server isolation and subscription checks

@tree.command(name="giveaway", description="Start a giveaway with advanced options")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    prize="What is the prize?",
    winners="How many winners?",
    duration="Duration (1m, 1h, 1d)",
    donor="The name of the giveaway donor (optional)",
    role="Optional role required to join (Pro feature)",
    min_account_age="Minimum account age in days (Pro feature)",
    min_server_time="Minimum time in server in days (Pro feature)"
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
    
    # Check Pro features access
    server_tier = get_server_tier(interaction.guild.id)
    
    if role:
        has_access, error_msg = check_feature_access(interaction.guild.id, 'role_requirement')
        if not has_access:
            await interaction.followup.send(error_msg, ephemeral=True)
            return
    
    if min_account_age:
        has_access, error_msg = check_feature_access(interaction.guild.id, 'account_age')
        if not has_access:
            await interaction.followup.send(error_msg, ephemeral=True)
            return
    
    if min_server_time:
        has_access, error_msg = check_feature_access(interaction.guild.id, 'server_time')
        if not has_access:
            await interaction.followup.send(error_msg, ephemeral=True)
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

    if min_account_age and (min_account_age < 0 or min_account_age > 3650):
        await interaction.followup.send("❌ Minimum account age must be between 0 and 3650 days.", ephemeral=True)
        return

    if min_server_time and (min_server_time < 0 or min_server_time > 365):
        await interaction.followup.send("❌ Minimum server time must be between 0 and 365 days.", ephemeral=True)
        return

    # Enhanced duration parsing
    total_seconds = 0
    duration_lower = duration.lower().strip()
    
    # Support multiple formats: 1d2h30m, 2h30m, 90m, etc.
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

    # Add subscription tier indicator
    tier_emoji = "✨" if server_tier == SubscriptionTier.PRO else "🆓"
    description_parts.append(f"\n{tier_emoji} **Powered by Givzy {server_tier.title()}**")

    embed = discord.Embed(
        title="🎉✨ GIVEAWAY! ✨🎉",
        description="\n".join(description_parts),
        color=discord.Color.from_rgb(255, 105, 180) if server_tier == SubscriptionTier.PRO else discord.Color.blue(),
        timestamp=end_time
    )
    embed.set_footer(text=f"Started by {interaction.user.display_name} • Ends")

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
        "original_duration_seconds": total_seconds,
        "subscription_tier": server_tier
    }
    
    asyncio.create_task(batch_save_database())
    logging.info(f"Enhanced giveaway {message_id_str} created in {interaction.guild.name} ({interaction.guild.id}) - ends in {duration} - Tier: {server_tier}")

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

    # SECURITY: Validate server access
    if not await validate_server_access(interaction, giveaway_data):
        await interaction.followup.send("❌ You can only manage giveaways from your current server.", ephemeral=True)
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

    # Confirmation dialog
    embed = discord.Embed(
        title="⚠️ Confirm Giveaway End",
        description=f"**Prize:** {giveaway_data['prize']}\n"
                   f"**Participants:** {len(giveaway_data.get('participants', []))}\n"
                   f"**Winners to pick:** {giveaway_data['winners']}\n\n"
                   f"Are you sure you want to end this giveaway?",
        color=discord.Color.orange()
    )
    
    view = ConfirmationView(interaction.user.id)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    
    await view.wait()
    if not view.confirmed:
        await interaction.edit_original_response(content="❌ Giveaway end cancelled.", embed=None, view=None)
        return

    participants = giveaway_data.get("participants", [])
    if not participants:
        await interaction.edit_original_response(
            content="❌ No one participated in this giveaway.", 
            embed=None, view=None
        )
        giveaway_data["status"] = "ended"
        giveaway_data["ended_at"] = datetime.now(timezone.utc).isoformat()
        giveaway_data["ended_by"] = interaction.user.id
        giveaways[message_id] = giveaway_data
        await save_database()
        return

    # Enhanced winner selection
    winners_count = min(len(participants), giveaway_data["winners"])
    winner_ids = random.sample(participants, winners_count)
    
    # Get winner objects for display
    winner_mentions = []
    winner_details = []
    
    for winner_id in winner_ids:
        try:
            user = await bot.fetch_user(int(winner_id))
            winner_mentions.append(f"<@{winner_id}>")
            winner_details.append({
                "id": winner_id,
                "name": user.display_name if hasattr(user, 'display_name') else user.name,
                "mention": f"<@{winner_id}>"
            })
        except:
            winner_mentions.append(f"<@{winner_id}>")
            winner_details.append({
                "id": winner_id,
                "name": "Unknown User",
                "mention": f"<@{winner_id}>"
            })

    # Update giveaway status
    giveaway_data["status"] = "ended"
    giveaway_data["ended_at"] = datetime.now(timezone.utc).isoformat()
    giveaway_data["ended_by"] = interaction.user.id
    giveaway_data["winner_ids"] = winner_ids
    giveaway_data["winner_details"] = winner_details
    giveaways[message_id] = giveaway_data
    await save_database()

    # Update original message with permission checks
    channel = bot.get_channel(giveaway_data["channel_id"])
    if channel and isinstance(channel, (discord.TextChannel, discord.Thread)):
        try:
            original_message = await channel.fetch_message(int(message_id))
            
            # Check if we have permission to edit the message
            if channel.permissions_for(interaction.guild.me).manage_messages:
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
            
            # Enhanced winner announcement with permission check
            if channel.permissions_for(interaction.guild.me).send_messages:
                winner_announcement = (
                    f"🎉 **GIVEAWAY ENDED!** 🎉\n\n"
                    f"🎁 **Prize:** {giveaway_data['prize']}\n"
                    f"🏆 **{'Winner' if len(winner_mentions) == 1 else 'Winners'}:** {' '.join(winner_mentions)}\n\n"
                    f"Congratulations! Please contact the giveaway host to claim your prize!"
                )
                
                await original_message.reply(winner_announcement)
            
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            logging.warning(f"Could not update original giveaway message {message_id}: {e}")

    await interaction.edit_original_response(
        content=f"✅ Giveaway ended successfully!\n🏆 Winners: {' '.join(winner_mentions)}", 
        embed=None, view=None
    )
    
    logging.info(f"Giveaway {message_id} ended in {interaction.guild.name} with {len(winner_ids)} winners")

@tree.command(name="reroll", description="Reroll winners for a giveaway")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    message_id="The message ID of the giveaway to reroll",
    new_winners="Number of new winners to pick (optional, uses original count if not specified)"
)
async def reroll_giveaway(interaction: discord.Interaction, message_id: str, new_winners: Optional[int] = None):
    """Reroll winners for an ended giveaway."""
    await interaction.response.defer(ephemeral=True)

    if not await validate_message_id(message_id):
        await interaction.followup.send("❌ Please provide a valid Discord message ID.", ephemeral=True)
        return

    giveaway_data = giveaways.get(message_id)
    if not giveaway_data:
        await interaction.followup.send("❌ Giveaway not found.", ephemeral=True)
        return

    # SECURITY: Validate server access
    if not await validate_server_access(interaction, giveaway_data):
        await interaction.followup.send("❌ You can only manage giveaways from your current server.", ephemeral=True)
        return

    if giveaway_data.get("status") != "ended":
        await interaction.followup.send("❌ This giveaway has not ended yet.", ephemeral=True)
        return

    # Permission check
    is_creator = giveaway_data.get("created_by") == interaction.user.id
    has_manage_perms = interaction.user.guild_permissions.manage_guild
    
    if not (is_creator or has_manage_perms):
        await interaction.followup.send("❌ Only the giveaway creator or users with Manage Server permission can reroll.", ephemeral=True)
        return

    participants = giveaway_data.get("participants", [])
    if not participants:
        await interaction.followup.send("❌ No participants to reroll from.", ephemeral=True)
        return

    # Determine number of winners
    winners_count = new_winners or giveaway_data["winners"]
    if winners_count > len(participants):
        winners_count = len(participants)

    # Pick new winners
    winner_ids = random.sample(participants, winners_count)
    winner_mentions = [f"<@{winner_id}>" for winner_id in winner_ids]

    # Update giveaway data
    giveaway_data["winner_ids"] = winner_ids
    giveaway_data["rerolled_at"] = datetime.now(timezone.utc).isoformat()
    giveaway_data["rerolled_by"] = interaction.user.id
    giveaway_data["reroll_count"] = giveaway_data.get("reroll_count", 0) + 1
    giveaways[message_id] = giveaway_data
    await save_database()

    # Update original message with permission checks
    channel = bot.get_channel(giveaway_data["channel_id"])
    if channel:
        try:
            original_message = await channel.fetch_message(int(message_id))
            
            # Check permissions before editing
            if channel.permissions_for(interaction.guild.me).manage_messages:
                rerolled_embed = discord.Embed(
                    title="🎉 GIVEAWAY REROLLED! 🎉",
                    description=f"🎁 **Prize:** {giveaway_data['prize']}\n"
                               f"✨ **Donor:** {giveaway_data['donor_name']}\n"
                               f"🏆 **New Winners:** {' '.join(winner_mentions)}\n"
                               f"👥 **Total Participants:** {len(participants)}\n"
                               f"🔄 **Rerolled by:** {interaction.user.mention}",
                    color=discord.Color.purple(),
                    timestamp=datetime.now(timezone.utc)
                )
                rerolled_embed.set_footer(text=f"Reroll #{giveaway_data['reroll_count']}")
                await original_message.edit(embed=rerolled_embed)
            
            # Reroll announcement with permission check
            if channel.permissions_for(interaction.guild.me).send_messages:
                await original_message.reply(
                    f"🔄 **GIVEAWAY REROLLED!**\n"
                    f"🏆 **New {'Winner' if len(winner_mentions) == 1 else 'Winners'}:** {' '.join(winner_mentions)}\n"
                    f"Congratulations! Please contact the giveaway host to claim your prize!"
                )
            
        except (discord.NotFound, discord.Forbidden):
            pass

    await interaction.followup.send(
        f"✅ Giveaway rerolled successfully!\n🏆 New winners: {' '.join(winner_mentions)}", 
        ephemeral=True
    )
    
    logging.info(f"Giveaway {message_id} rerolled in {interaction.guild.name}")

@tree.command(name="cancelgiveaway", description="Cancel an active giveaway")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(message_id="The message ID of the giveaway to cancel")
async def cancel_giveaway(interaction: discord.Interaction, message_id: str):
    """Cancel a giveaway with confirmation."""
    await interaction.response.defer(ephemeral=True)

    if not await validate_message_id(message_id):
        await interaction.followup.send("❌ Please provide a valid Discord message ID.", ephemeral=True)
        return

    giveaway_data = giveaways.get(message_id)
    if not giveaway_data:
        await interaction.followup.send("❌ Giveaway not found.", ephemeral=True)
        return

    # SECURITY: Validate server access
    if not await validate_server_access(interaction, giveaway_data):
        await interaction.followup.send("❌ You can only manage giveaways from your current server.", ephemeral=True)
        return

    if giveaway_data.get("status") != "active":
        await interaction.followup.send(f"❌ This giveaway is already {giveaway_data.get('status', 'inactive')}.", ephemeral=True)
        return

    # Enhanced permission check
    is_creator = giveaway_data.get("created_by") == interaction.user.id
    has_manage_perms = interaction.user.guild_permissions.manage_guild
    
    if not (is_creator or has_manage_perms):
        await interaction.followup.send("❌ Only the giveaway creator or users with Manage Server permission can cancel this giveaway.", ephemeral=True)
        return

    # Confirmation dialog
    embed = discord.Embed(
        title="⚠️ Confirm Giveaway Cancellation",
        description=f"**Prize:** {giveaway_data['prize']}\n"
                   f"**Participants:** {len(giveaway_data.get('participants', []))}\n\n"
                   f"Are you sure you want to cancel this giveaway?\n"
                   f"This action cannot be undone!",
        color=discord.Color.red()
    )
    
    view = ConfirmationView(interaction.user.id)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    
    await view.wait()
    if not view.confirmed:
        await interaction.edit_original_response(content="❌ Cancellation aborted.", embed=None, view=None)
        return

    # Cancel the giveaway
    giveaway_data["status"] = "cancelled"
    giveaway_data["cancelled_at"] = datetime.now(timezone.utc).isoformat()
    giveaway_data["cancelled_by"] = interaction.user.id
    giveaways[message_id] = giveaway_data
    await save_database()

    # Update original message with permission checks
    channel = bot.get_channel(giveaway_data["channel_id"])
    if channel and isinstance(channel, (discord.TextChannel, discord.Thread)):
        try:
            original_message = await channel.fetch_message(int(message_id))
            
            # Check permissions before editing
            if channel.permissions_for(interaction.guild.me).manage_messages:
                cancelled_embed = discord.Embed(
                    title="🚫 GIVEAWAY CANCELLED 🚫",
                    description=f"🎁 **Prize:** {giveaway_data['prize']}\n"
                               f"❌ **Reason:** Cancelled by {interaction.user.mention}\n"
                               f"👥 **Participants:** {len(giveaway_data.get('participants', []))}",
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc)
                )
                cancelled_embed.set_footer(text="Giveaway cancelled")
                await original_message.edit(embed=cancelled_embed, view=None)
            
        except (discord.NotFound, discord.Forbidden):
            pass

    await interaction.edit_original_response(
        content="✅ Giveaway cancelled successfully.", 
        embed=None, view=None
    )
    
    logging.info(f"Giveaway {message_id} cancelled in {interaction.guild.name}")

# Enhanced event handlers and background tasks

@bot.event
async def on_ready():
    """Enhanced startup sequence with proper view restoration."""
    logging.info(f"🚀 Givzy Bot logged in as {bot.user}")
    
    # Load all data from database
    await load_database()
    await load_subscriptions(bot)
    
    # Add subscription commands
    add_subscription_commands(tree, bot)
    
    # Sync commands
    try:
        synced = await tree.sync()
        logging.info(f"✅ Synced {len(synced)} slash commands.")
    except Exception as e:
        logging.error(f"❌ Failed to sync commands: {e}")

    # Re-attach views for active giveaways - CRITICAL FIX
    active_count = 0
    failed_count = 0
    
    logging.info("🔧 Re-attaching views for active giveaways...")
    
    for message_id, data in list(giveaways.items()):
        if data.get("status") == "active":
            try:
                # Validate that the message ID is valid
                if await validate_message_id(message_id):
                    # Create and attach the view
                    view = JoinView(message_id=message_id)
                    bot.add_view(view, message_id=int(message_id))
                    active_count += 1
                    
                    # Log details for verification
                    server_name = data.get("server_name", "Unknown Server")
                    prize = data.get("prize", "Unknown Prize")
                    participants = len(data.get("participants", []))
                    logging.info(f"   ✅ Re-attached view for: {prize} in {server_name} ({participants} participants)")
                else:
                    logging.warning(f"   ❌ Invalid message ID format: {message_id}")
                    failed_count += 1
                    
            except Exception as e:
                logging.warning(f"   ❌ Could not re-attach view for giveaway {message_id}: {e}")
                failed_count += 1
    
    logging.info(f"🎉 View restoration complete: {active_count} views attached, {failed_count} failed")
    
    # Log comprehensive startup statistics
    total_giveaways = len(giveaways)
    total_servers = len(set(g.get("server_id") for g in giveaways.values() if g.get("server_id")))
    
    logging.info(f"📊 Givzy Bot Statistics:")
    logging.info(f"   🎪 Total Giveaways: {total_giveaways}")
    logging.info(f"   🎯 Active Giveaways: {active_count}")
    logging.info(f"   🏰 Servers: {total_servers}")
    
    # Log active giveaways for verification
    if active_count > 0:
        logging.info("   Active giveaway details:")
        for msg_id, data in giveaways.items():
            if data.get("status") == "active":
                server_name = data.get("server_name", "Unknown")
                prize = data.get("prize", "Unknown Prize")
                participants = len(data.get("participants", []))
                tier = data.get("subscription_tier", "free")
                logging.info(f"     - {msg_id}: {prize} in {server_name} ({participants} participants) [{tier}]")
    
    # Start background tasks
    check_giveaways.start()
    database_maintenance.start()
    
    logging.info("🎊 Givzy Bot is fully ready!")

@tasks.loop(minutes=1)
async def check_giveaways():
    """Enhanced giveaway expiration checker with better error handling."""
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
            await save_database()
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
            await save_database()
            return
        except discord.Forbidden:
            logging.warning(f"No permission to access message {message_id}")
            data["status"] = "ended"
            data["ended_at"] = datetime.now(timezone.utc).isoformat()
            data["ended_by"] = "automatic_no_permission"
            giveaways[message_id] = data
            await save_database()
            return
        
        # Update giveaway status
        data["status"] = "ended"
        data["ended_at"] = datetime.now(timezone.utc).isoformat()
        data["ended_by"] = "automatic"
        
        if not participants:
            # No participants case
            if channel.permissions_for(channel.guild.me).manage_messages:
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
            
            if channel.permissions_for(channel.guild.me).send_messages:
                await message.reply("😔 This giveaway ended with no participants. Better luck next time!")
            
        else:
            # Pick winners
            winners_count = min(len(participants), data["winners"])
            winner_ids = random.sample(participants, winners_count)
            winner_mentions = [f"<@{uid}>" for uid in winner_ids]
            
            data["winner_ids"] = winner_ids
            
            # Create winner details for better tracking
            winner_details = []
            for winner_id in winner_ids:
                try:
                    user = await bot.fetch_user(int(winner_id))
                    winner_details.append({
                        "id": winner_id,
                        "name": user.display_name if hasattr(user, 'display_name') else user.name,
                        "username": str(user)
                    })
                except:
                    winner_details.append({
                        "id": winner_id,
                        "name": "Unknown User",
                        "username": "Unknown#0000"
                    })
            
            data["winner_details"] = winner_details
            
            # Update message with results - check permissions first
            if channel.permissions_for(channel.guild.me).manage_messages:
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
            
            # Enhanced winner announcement - check permissions first
            if channel.permissions_for(channel.guild.me).send_messages:
                winner_announcement = (
                    f"🎊 **GIVEAWAY RESULTS ARE IN!** 🎊\n\n"
                    f"🎁 **Prize:** {data['prize']}\n"
                    f"🏆 **{'Winner' if len(winner_mentions) == 1 else 'Winners'}:** {' '.join(winner_mentions)}\n\n"
                    f"🎉 Congratulations! Please contact {data['donor_name']} or a server admin to claim your prize!\n"
                    f"📩 Make sure your DMs are open so we can contact you!"
                )
                
                try:
                    await message.reply(winner_announcement)
                except discord.HTTPException:
                    # If reply fails, try sending a new message
                    try:
                        await channel.send(winner_announcement)
                    except discord.HTTPException as e:
                        logging.error(f"Could not send winner announcement for {message_id}: {e}")
        
        # Save updated data
        giveaways[message_id] = data
        await save_database()
        
        server_name = data.get('server_name', 'Unknown Server')
        winner_count = len(winner_ids) if participants else 0
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
            await save_database()
        except:
            pass  # Prevent cascade failures

@tasks.loop(hours=24)  # Run daily
async def database_maintenance():
    """Perform daily database maintenance and cleanup."""
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
                    # Invalid date format, keep the entry
                    continue
        
        # Save cleaned database
        if cleaned_count > 0:
            await save_database()
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
    """Enhanced guild join handler with analytics."""
    logging.info(f"🆕 Joined new server: {guild.name} ({guild.id}) with {guild.member_count} members")
    
    # Try to send a welcome message to the system channel or first available channel
    welcome_embed = discord.Embed(
        title="🎉 Thanks for adding Givzy!",
        description=(
            "I'm ready to help you manage amazing giveaways with complete server isolation!\n\n"
            "**🚀 Quick Start:**\n"
            "• Use `/giveaway` to create your first giveaway\n"
            "• Use `/subscription` to check your current plan\n"
            "• Use `/buy` to upgrade to Pro for advanced features\n\n"
            "**🆓 Free Tier Features:**\n"
            "• Basic giveaway creation and management\n"
            "• Winner selection and rerolls\n"
            "• Server-specific data isolation\n\n"
            "**✨ Pro Tier Features ($2/month):**\n"
            "• Role requirements for giveaways\n"
            "• Minimum account age restrictions\n"
            "• Minimum server time requirements\n"
            "• Enhanced security and moderation\n\n"
            "**🔒 Privacy & Security:**\n"
            "• All giveaway data is server-specific and private\n"
            "• No cross-server data access or sharing\n"
            "• Only server admins can manage giveaways\n"
            "• Complete isolation between different servers\n\n"
            "**🛡️ Permissions:**\n"
            "Only users with 'Manage Server' permission can create and manage giveaways."
        ),
        color=discord.Color.green()
    )
    
    # Try to find a suitable channel to send the welcome message
    target_channel = None
    if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        target_channel = guild.system_channel
    else:
        # Find first text channel we can send messages to
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                target_channel = channel
                break
    
    if target_channel:
        try:
            await target_channel.send(embed=welcome_embed)
        except discord.HTTPException:
            pass  # Ignore if we can't send messages

@bot.event
async def on_guild_remove(guild):
    """Enhanced guild leave handler with cleanup."""
    logging.info(f"👋 Left server: {guild.name} ({guild.id})")
    
    # Count how many giveaways were in this server
    server_giveaways = sum(1 for g in giveaways.values() if g.get("server_id") == guild.id)
    if server_giveaways > 0:
        logging.info(f"📊 Had {server_giveaways} giveaways in {guild.name}")

@bot.event
async def on_command_error(ctx, error):
    """Enhanced error handling for commands."""
    if isinstance(error, commands.CommandNotFound):
        return  # Ignore unknown commands
    
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.", delete_after=10)
        return
    
    logging.error(f"Command error in {ctx.guild}: {error}")

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
    
    if isinstance(error, app_commands.BotMissingPermissions):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ I'm missing permissions to perform this action. Please check my role permissions.",
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
    raise ValueError("DISCORD_TOKEN is not set in the environment.")

# Start keep alive system and run the bot
keep_alive()
bot.run(DISCORD_TOKEN)
