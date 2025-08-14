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

# Global data structures - now server-isolated
giveaways = {}
giveaway_templates = {}
blacklisted_users = {}
pending_database_save = False
last_database_save = datetime.now()

class GiveawayTemplate:
    """Class to handle giveaway templates"""
    def __init__(self, name: str, prize: str, winners: int, duration: str, 
                 donor: str = None, required_role_id: int = None, 
                 min_account_age_days: int = 0, min_server_days: int = 0):
        self.name = name
        self.prize = prize
        self.winners = winners
        self.duration = duration
        self.donor = donor
        self.required_role_id = required_role_id
        self.min_account_age_days = min_account_age_days
        self.min_server_days = min_server_days
    
    def to_dict(self):
        return {
            'name': self.name,
            'prize': self.prize,
            'winners': self.winners,
            'duration': self.duration,
            'donor': self.donor,
            'required_role_id': self.required_role_id,
            'min_account_age_days': self.min_account_age_days,
            'min_server_days': self.min_server_days
        }
    
    @classmethod
    def from_dict(cls, data):
        return cls(**data)

def get_server_giveaways(server_id: int) -> Dict:
    """Get giveaways for a specific server only"""
    return {k: v for k, v in giveaways.items() if v.get("server_id") == server_id}

def get_server_templates(server_id: int) -> Dict:
    """Get templates for a specific server only"""
    return giveaway_templates.get(str(server_id), {})

def get_server_blacklist(server_id: int) -> Dict:
    """Get blacklist for a specific server only"""
    return blacklisted_users.get(str(server_id), {})

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
    
    # Check if user is blacklisted (server-specific only)
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
    """Load giveaway data from the database channel with improved error handling."""
    global giveaways, giveaway_templates, blacklisted_users
    
    try:
        db_channel = bot.get_channel(DATABASE_CHANNEL_ID)
        if not db_channel:
            logging.error(f"Database channel {DATABASE_CHANNEL_ID} not found!")
            return

        # Initialize with empty data
        giveaways = {}
        giveaway_templates = {}
        blacklisted_users = {}
        
        # Look for the most recent valid database message
        json_parts = []
        backup_data = None
        
        async for message in db_channel.history(limit=300):
            if message.author != bot.user:
                continue
            
            # Check for single JSON message
            if message.content.startswith("```json") and message.content.endswith("```"):
                try:
                    json_content = message.content[7:-3]  # Remove ```json and ```
                    data = json.loads(json_content)
                    
                    # Load main giveaway data
                    if "giveaways" in data:
                        giveaways = data["giveaways"]
                        giveaway_templates = data.get("templates", {})
                        blacklisted_users = data.get("blacklisted", {})
                    else:
                        # Legacy format - just giveaways
                        giveaways = data
                    
                    logging.info(f"Loaded database: {len(giveaways)} giveaways, {len(giveaway_templates)} templates")
                    return
                    
                except json.JSONDecodeError as e:
                    logging.warning(f"JSON decode error in message {message.id}: {e}")
                    if not backup_data:  # Keep first valid partial data as backup
                        backup_data = message.content
                    continue
            
            # Check for multi-part messages
            if "Part" in message.content and "```json" in message.content:
                try:
                    start = message.content.find("```json") + 7
                    end = message.content.rfind("```")
                    if start > 6 and end > start:
                        json_parts.append(message.content[start:end])
                except Exception as e:
                    logging.warning(f"Error parsing multi-part message: {e}")
                    continue
        
        # Try to combine multi-part JSON
        if json_parts:
            try:
                combined_json = "".join(json_parts)
                data = json.loads(combined_json)
                
                if "giveaways" in data:
                    giveaways = data["giveaways"]
                    giveaway_templates = data.get("templates", {})
                    blacklisted_users = data.get("blacklisted", {})
                else:
                    giveaways = data
                
                logging.info(f"Loaded from {len(json_parts)} parts: {len(giveaways)} giveaways")
                return
                
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse multi-part JSON: {e}")
        
        # If all else fails, try backup data
        if backup_data:
            try:
                json_content = backup_data[7:-3]
                giveaways = json.loads(json_content)
                logging.warning("Loaded from backup data - some data might be missing")
                return
            except:
                pass
        
        logging.info("No valid database found, starting with empty database.")
        
    except Exception as e:
        logging.error(f"Critical error loading database: {e}")
        # Initialize with empty data to prevent crashes
        giveaways = {}
        giveaway_templates = {}
        blacklisted_users = {}

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
            "templates": giveaway_templates,
            "blacklisted": blacklisted_users,
            "metadata": {
                "version": "2.1",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "total_giveaways": len(giveaways),
                "active_giveaways": sum(1 for g in giveaways.values() if g.get("status") == "active"),
                "total_servers": len(set(g.get("server_id") for g in giveaways.values() if g.get("server_id")))
            }
        }
        
        json_content = json.dumps(database_data, indent=2)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Calculate content hash for integrity
        content_hash = hashlib.md5(json_content.encode()).hexdigest()[:8]
        
        # Check if content is too large for Discord
        if len(json_content) > 1900:
            # Split into chunks
            chunk_size = 1900
            chunks = [json_content[i:i+chunk_size] for i in range(0, len(json_content), chunk_size)]
            
            # Send header embed
            embed = discord.Embed(
                title="🗄️ Secure Giveaway Database Backup",
                description=f"**Database Version:** 2.1 (Secure Multi-Server)\n"
                           f"**Total Giveaways:** {database_data['metadata']['total_giveaways']}\n"
                           f"**Active:** {database_data['metadata']['active_giveaways']}\n"
                           f"**Servers:** {database_data['metadata']['total_servers']}\n"
                           f"**Templates:** {len(giveaway_templates)}\n"
                           f"**Last Updated:** {timestamp}\n"
                           f"**Split into {len(chunks)} parts**\n"
                           f"**Hash:** `{content_hash}`",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            
            await db_channel.send(embed=embed)
            
            # Send JSON chunks
            for i, chunk in enumerate(chunks):
                chunk_message = f"**Part {i+1}/{len(chunks)}:**\n```json\n{chunk}\n```"
                await db_channel.send(chunk_message)
            
            logging.info(f"Database saved in {len(chunks)} parts (hash: {content_hash})")
        else:
            # Small database
            message_content = f"```json\n{json_content}\n```"
            embed = discord.Embed(
                title="🗄️ Secure Giveaway Database Backup",
                description=f"**Database Version:** 2.1 (Secure Multi-Server)\n"
                           f"**Total Giveaways:** {database_data['metadata']['total_giveaways']}\n"
                           f"**Active:** {database_data['metadata']['active_giveaways']}\n"
                           f"**Servers:** {database_data['metadata']['total_servers']}\n"
                           f"**Templates:** {len(giveaway_templates)}\n"
                           f"**Last Updated:** {timestamp}\n"
                           f"**Hash:** `{content_hash}`",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            
            await db_channel.send(content=message_content, embed=embed)
            logging.info(f"Database saved successfully (hash: {content_hash})")
        
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

class CreateTemplateModal(Modal, title="Create Giveaway Template"):
    """Modal for creating giveaway templates"""
    def __init__(self):
        super().__init__()
    
    name = TextInput(
        label="Template Name",
        placeholder="e.g., 'Weekly Nitro Giveaway'",
        max_length=50,
        required=True
    )
    
    prize = TextInput(
        label="Prize",
        placeholder="e.g., 'Discord Nitro Classic'",
        max_length=100,
        required=True
    )
    
    duration = TextInput(
        label="Duration",
        placeholder="e.g., '7d' for 7 days",
        max_length=10,
        required=True
    )
    
    winners = TextInput(
        label="Number of Winners",
        placeholder="e.g., '1'",
        max_length=3,
        required=True
    )
    
    donor = TextInput(
        label="Donor Name (Optional)",
        placeholder="Leave blank to use your display name",
        max_length=50,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Validate inputs
            winners_count = int(self.winners.value)
            if winners_count <= 0:
                await interaction.response.send_message("❌ Number of winners must be positive.", ephemeral=True)
                return
            
            # Validate duration format
            if not re.fullmatch(r'\d+[smhd]', self.duration.value.lower()):
                await interaction.response.send_message("❌ Invalid duration format. Use formats like `30s`, `5m`, `2h`, or `1d`.", ephemeral=True)
                return
            
            # Create template (server-specific)
            server_id = str(interaction.guild.id)
            if server_id not in giveaway_templates:
                giveaway_templates[server_id] = {}
            
            template_key = f"{server_id}_{self.name.value.lower().replace(' ', '_')}"
            template = GiveawayTemplate(
                name=self.name.value,
                prize=self.prize.value,
                winners=winners_count,
                duration=self.duration.value.lower(),
                donor=self.donor.value or None
            )
            
            giveaway_templates[server_id][template_key] = template.to_dict()
            await save_database()
            
            embed = discord.Embed(
                title="✅ Template Created",
                description=f"**Name:** {self.name.value}\n"
                           f"**Prize:** {self.prize.value}\n"
                           f"**Duration:** {self.duration.value}\n"
                           f"**Winners:** {winners_count}",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number for winners.", ephemeral=True)
        except Exception as e:
            logging.error(f"Error creating template: {e}")
            await interaction.response.send_message("❌ An error occurred while creating the template.", ephemeral=True)

# Enhanced slash commands with server isolation

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
    
    asyncio.create_task(batch_save_database())
    logging.info(f"Enhanced giveaway {message_id_str} created in {interaction.guild.name} ({interaction.guild.id}) - ends in {duration}")

@tree.command(name="giveaway_template", description="Create a giveaway from a template")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_template(interaction: discord.Interaction):
    """Create a giveaway using a saved template."""
    server_templates = get_server_templates(interaction.guild.id)
    
    if not server_templates:
        await interaction.response.send_message(
            "❌ No templates found for this server. Use `/create_template` to create one.",
            ephemeral=True
        )
        return
    
    # Show template selection (simplified for now - could be enhanced with select menu)
    template_list = []
    for template_data in server_templates.values():
        template_list.append(f"• **{template_data['name']}** - {template_data['prize']} ({template_data['duration']})")
    
    embed = discord.Embed(
        title="📋 Available Templates",
        description="\n".join(template_list),
        color=discord.Color.blue()
    )
    embed.set_footer(text="Use the template name exactly as shown with /use_template <name>")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="use_template", description="Use a specific template to create a giveaway")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(template_name="Name of the template to use")
async def use_template(interaction: discord.Interaction, template_name: str):
    """Create a giveaway using a specific template."""
    server_templates = get_server_templates(interaction.guild.id)
    
    # Find template (server-specific only)
    template_data = None
    for key, data in server_templates.items():
        if data['name'].lower() == template_name.lower():
            template_data = data
            break
    
    if not template_data:
        await interaction.response.send_message(f"❌ Template '{template_name}' not found.", ephemeral=True)
        return
    
    # Create giveaway from template (reuse giveaway logic)
    await giveaway(
        interaction=interaction,
        prize=template_data['prize'],
        winners=template_data['winners'],
        duration=template_data['duration'],
        donor=template_data.get('donor'),
        role=interaction.guild.get_role(template_data['required_role_id']) if template_data.get('required_role_id') else None,
        min_account_age=template_data.get('min_account_age_days'),
        min_server_time=template_data.get('min_server_days')
    )

@tree.command(name="create_template", description="Create a giveaway template")
@app_commands.checks.has_permissions(manage_guild=True)
async def create_template(interaction: discord.Interaction):
    """Create a giveaway template for reuse."""
    modal = CreateTemplateModal()
    await interaction.response.send_modal(modal)

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

@tree.command(name="blacklist", description="Blacklist a user from joining giveaways")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    user="The user to blacklist",
    reason="Reason for blacklisting (optional)"
)
async def blacklist_user(interaction: discord.Interaction, user: discord.Member, reason: Optional[str] = None):
    """Add a user to the giveaway blacklist (server-specific)."""
    server_id = str(interaction.guild.id)
    user_id = str(user.id)
    
    if server_id not in blacklisted_users:
        blacklisted_users[server_id] = {}
    
    if user_id in blacklisted_users[server_id]:
        await interaction.response.send_message(f"❌ {user.mention} is already blacklisted.", ephemeral=True)
        return
    
    blacklisted_users[server_id][user_id] = {
        "user_name": str(user),
        "reason": reason or "No reason provided",
        "blacklisted_at": datetime.now(timezone.utc).isoformat(),
        "blacklisted_by": interaction.user.id
    }
    
    await save_database()
    
    embed = discord.Embed(
        title="🚫 User Blacklisted",
        description=f"**User:** {user.mention}\n**Reason:** {reason or 'No reason provided'}",
        color=discord.Color.red()
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    logging.info(f"User {user} blacklisted in {interaction.guild.name}")

@tree.command(name="unblacklist", description="Remove a user from the giveaway blacklist")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(user="The user to unblacklist")
async def unblacklist_user(interaction: discord.Interaction, user: discord.Member):
    """Remove a user from the giveaway blacklist (server-specific)."""
    server_id = str(interaction.guild.id)
    user_id = str(user.id)
    
    if server_id not in blacklisted_users or user_id not in blacklisted_users[server_id]:
        await interaction.response.send_message(f"❌ {user.mention} is not blacklisted.", ephemeral=True)
        return
    
    del blacklisted_users[server_id][user_id]
    
    # Clean up empty server entries
    if not blacklisted_users[server_id]:
        del blacklisted_users[server_id]
    
    await save_database()
    
    embed = discord.Embed(
        title="✅ User Unblacklisted",
        description=f"**User:** {user.mention}\nThey can now join giveaways again.",
        color=discord.Color.green()
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    logging.info(f"User {user} unblacklisted in {interaction.guild.name}")

@tree.command(name="giveawaystats", description="View comprehensive giveaway statistics for this server")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_stats(interaction: discord.Interaction):
    """Show enhanced giveaway statistics for the current server only."""
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server!", ephemeral=True)
        return

    # SECURITY: Only get data from current server
    server_giveaways = get_server_giveaways(interaction.guild.id)
    server_templates = get_server_templates(interaction.guild.id)
    server_blacklist = get_server_blacklist(interaction.guild.id)
    
    # Calculate statistics (server-specific only)
    total = len(server_giveaways)
    active = sum(1 for g in server_giveaways.values() if g.get("status") == "active")
    ended = sum(1 for g in server_giveaways.values() if g.get("status") == "ended")
    cancelled = sum(1 for g in server_giveaways.values() if g.get("status") == "cancelled")
    
    # Calculate participation statistics (server-specific only)
    total_participants = sum(len(g.get("participants", [])) for g in server_giveaways.values())
    total_winners = sum(len(g.get("winner_ids", [])) for g in server_giveaways.values())
    
    embed = discord.Embed(
        title=f"📊 Server Giveaway Statistics - {interaction.guild.name}",
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
    
    # Templates and blacklist info (server-specific)
    template_count = len(server_templates)
    blacklist_count = len(server_blacklist)
    embed.add_field(name="📋 Templates", value=str(template_count), inline=True)
    embed.add_field(name="🚫 Blacklisted Users", value=str(blacklist_count), inline=True)
    
    # Average participation (server-specific)
    avg_participation = round(total_participants / total, 1) if total > 0 else 0
    embed.add_field(name="📈 Avg Participants", value=str(avg_participation), inline=True)

    # Recent activity (server-specific)
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
            recent_text += f"{status_emoji} **{data['prize'][:30]}{'...' if len(data['prize']) > 30 else ''}** ({participant_count} participants)\n"
        
        embed.add_field(name="🕒 Recent Giveaways", value=recent_text, inline=False)

    embed.set_footer(text="Statistics are server-specific and private")
    
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="listblacklist", description="View blacklisted users for this server")
@app_commands.checks.has_permissions(manage_guild=True)
async def list_blacklist(interaction: discord.Interaction):
    """Show the current blacklist for this server only."""
    server_blacklist = get_server_blacklist(interaction.guild.id)
    
    if not server_blacklist:
        await interaction.response.send_message("✅ No users are currently blacklisted from giveaways in this server.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title=f"🚫 Blacklisted Users - {interaction.guild.name}",
        color=discord.Color.red()
    )
    
    blacklist_text = ""
    for user_id, data in list(server_blacklist.items())[:10]:  # Limit to 10 for embed space
        blacklist_text += f"<@{user_id}> - {data.get('reason', 'No reason')}\n"
    
    if len(server_blacklist) > 10:
        blacklist_text += f"\n... and {len(server_blacklist) - 10} more users."
    
    embed.description = blacklist_text
    embed.set_footer(text=f"Total blacklisted in this server: {len(server_blacklist)}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="giveaway_info", description="Get detailed information about a specific giveaway")
@app_commands.describe(message_id="The message ID of the giveaway to check")
async def giveaway_info(interaction: discord.Interaction, message_id: str):
    """Show detailed information about a specific giveaway (server-specific only)."""
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
        await interaction.followup.send("❌ You can only view giveaways from your current server.", ephemeral=True)
        return

    # Create detailed embed
    embed = discord.Embed(
        title="🎉 Giveaway Information",
        color=discord.Color.blue()
    )
    
    # Basic information
    embed.add_field(name="🎁 Prize", value=giveaway_data['prize'], inline=False)
    embed.add_field(name="✨ Donor", value=giveaway_data['donor_name'], inline=True)
    embed.add_field(name="🏆 Winners", value=str(giveaway_data['winners']), inline=True)
    embed.add_field(name="📊 Status", value=giveaway_data.get('status', 'unknown').title(), inline=True)
    
    # Participation info
    participants = giveaway_data.get('participants', [])
    embed.add_field(name="👥 Participants", value=str(len(participants)), inline=True)
    
    # Server info (current server only)
    embed.add_field(name="🏠 Server", value=interaction.guild.name, inline=True)
    embed.add_field(name="📝 Message ID", value=message_id, inline=True)
    
    # Time information
    created_at = giveaway_data.get('created_at')
    if created_at:
        created_timestamp = int(datetime.fromisoformat(created_at.replace('Z', '+00:00')).timestamp())
        embed.add_field(name="⏰ Created", value=f"<t:{created_timestamp}:R>", inline=True)
    
    end_time = giveaway_data.get('end_time')
    if end_time:
        end_timestamp = int(datetime.fromisoformat(end_time.replace('Z', '+00:00')).timestamp())
        embed.add_field(name="🏁 Ends/Ended", value=f"<t:{end_timestamp}:R>", inline=True)
    
    # Requirements
    requirements = []
    if giveaway_data.get('required_role'):
        try:
            role = interaction.guild.get_role(giveaway_data['required_role'])
            requirements.append(f"Role: {role.mention if role else 'Deleted Role'}")
        except:
            requirements.append("Role: Unknown")
    
    if giveaway_data.get('min_account_age_days', 0) > 0:
        requirements.append(f"Account Age: {giveaway_data['min_account_age_days']} days")
    
    if giveaway_data.get('min_server_days', 0) > 0:
        requirements.append(f"Server Time: {giveaway_data['min_server_days']} days")
    
    if requirements:
        embed.add_field(name="📋 Requirements", value="\n".join(requirements), inline=False)
    
    # Winner information
    if giveaway_data.get('status') == 'ended' and giveaway_data.get('winner_ids'):
        winner_mentions = [f"<@{uid}>" for uid in giveaway_data['winner_ids']]
        embed.add_field(name="🏆 Winners", value=" ".join(winner_mentions), inline=False)
        
        ended_at = giveaway_data.get('ended_at')
        if ended_at:
            ended_timestamp = int(datetime.fromisoformat(ended_at.replace('Z', '+00:00')).timestamp())
            embed.add_field(name="🏁 Ended At", value=f"<t:{ended_timestamp}:f>", inline=True)
        
        if giveaway_data.get('reroll_count', 0) > 0:
            embed.add_field(name="🔄 Rerolls", value=str(giveaway_data['reroll_count']), inline=True)

    # Creator info
    try:
        creator = await bot.fetch_user(giveaway_data['created_by'])
        embed.set_footer(text=f"Created by {creator.display_name}")
    except:
        embed.set_footer(text="Creator information unavailable")

    await interaction.followup.send(embed=embed, ephemeral=True)

# Enhanced event handlers and background tasks

@bot.event
async def on_ready():
    """Enhanced startup sequence."""
    logging.info(f"🚀 Secure Multi-Server Giveaway Bot logged in as {bot.user}")
    
    # Load all data from database
    await load_database()
    
    # Sync commands
    try:
        synced = await tree.sync()
        logging.info(f"✅ Synced {len(synced)} slash commands.")
    except Exception as e:
        logging.error(f"❌ Failed to sync commands: {e}")

    # Re-attach views for active giveaways
    active_count = 0
    for message_id, data in giveaways.items():
        if data.get("status") == "active":
            try:
                bot.add_view(JoinView(message_id=message_id), message_id=int(message_id))
                active_count += 1
            except Exception as e:
                logging.warning(f"Could not re-attach view for giveaway {message_id}: {e}")
    
    logging.info(f"🎉 Re-attached {active_count} active giveaway views")
    logging.info(f"📊 Managing {len(giveaways)} total giveaways across {len(set(g.get('server_id') for g in giveaways.values() if g.get('server_id')))} servers")
    logging.info(f"📋 {sum(len(templates) for templates in giveaway_templates.values())} templates available")
    logging.info(f"🚫 {sum(len(bl) for bl in blacklisted_users.values())} blacklisted users total")
    
    # Start background tasks
    check_giveaways.start()
    database_maintenance.start()
    
    logging.info("🎊 Secure Multi-Server Giveaway Bot is fully ready!")

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
        logging.info(f"🎉 Auto-ended giveaway {message_id} in {server_name} - {len(winner_ids) if participants else 0} winners")
        
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
        
        # Clean up empty blacklist entries
        blacklist_cleaned = 0
        for server_id in list(blacklisted_users.keys()):
            if not blacklisted_users[server_id]:
                del blacklisted_users[server_id]
                blacklist_cleaned += 1
        
        # Clean up empty template entries
        template_cleaned = 0
        for server_id in list(giveaway_templates.keys()):
            if not giveaway_templates[server_id]:
                del giveaway_templates[server_id]
                template_cleaned += 1
        
        # Save cleaned database
        if cleaned_count > 0 or blacklist_cleaned > 0 or template_cleaned > 0:
            await save_database()
            logging.info(f"🧹 Maintenance complete: {cleaned_count} old giveaways, {blacklist_cleaned} blacklist entries, {template_cleaned} template entries cleaned")
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
        title="🎉 Thanks for adding Secure Giveaway Bot!",
        description=(
            "I'm ready to help you manage amazing giveaways with complete server isolation!\n\n"
            "**🚀 Quick Start:**\n"
            "• Use `/giveaway` to create your first giveaway\n"
            "• Use `/create_template` to save common setups\n"
            "• Use `/giveawaystats` to view your server's statistics\n\n"
            "**🔒 Privacy & Security:**\n"
            "• All giveaway data is server-specific and private\n"
            "• No cross-server data access or sharing\n"
            "• Only server admins can manage giveaways\n"
            "• Complete isolation between different servers\n\n"
            "**✨ Enhanced Features:**\n"
            "• Role requirements and user restrictions\n"
            "• Automatic winner selection and rerolls\n"
            "• User blacklisting and templates\n"
            "• Comprehensive server-specific statistics\n\n"
            "**🔒 Permissions Needed:**\n"
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

# Additional utility commands for enhanced functionality (server-isolated)

@tree.command(name="export_giveaways", description="Export server giveaway data (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def export_giveaways(interaction: discord.Interaction):
    """Export all giveaway data for the current server only."""
    await interaction.response.defer(ephemeral=True)
    
    server_id = interaction.guild.id
    server_giveaways = get_server_giveaways(server_id)
    
    if not server_giveaways:
        await interaction.followup.send("❌ No giveaways found for this server.", ephemeral=True)
        return
    
    # Create export data (server-specific only)
    export_data = {
        "server_name": interaction.guild.name,
        "server_id": server_id,
        "export_date": datetime.now(timezone.utc).isoformat(),
        "giveaways": server_giveaways,
        "templates": get_server_templates(server_id),
        "blacklisted_users": get_server_blacklist(server_id),
        "statistics": {
            "total_giveaways": len(server_giveaways),
            "active": sum(1 for g in server_giveaways.values() if g.get("status") == "active"),
            "ended": sum(1 for g in server_giveaways.values() if g.get("status") == "ended"),
            "cancelled": sum(1 for g in server_giveaways.values() if g.get("status") == "cancelled"),
            "total_participants": sum(len(g.get("participants", [])) for g in server_giveaways.values())
        },
        "privacy_notice": "This export contains only data from your server. No cross-server data is included."
    }
    
    # Create JSON file content
    json_content = json.dumps(export_data, indent=2)
    
    # Create file and send
    import io
    filename = f"giveaways_export_{interaction.guild.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    discord_file = discord.File(io.BytesIO(json_content.encode()), filename=filename)
    
    embed = discord.Embed(
        title="📤 Server Giveaway Data Export",
        description=f"**Server:** {interaction.guild.name}\n"
                   f"**Total Giveaways:** {len(server_giveaways)}\n"
                   f"**Export Date:** <t:{int(datetime.now().timestamp())}:f>\n"
                   f"**Privacy:** Server-specific data only",
        color=discord.Color.blue()
    )
    
    await interaction.followup.send(embed=embed, file=discord_file, ephemeral=True)
    logging.info(f"Exported giveaway data for {interaction.guild.name}")

@tree.command(name="cleanup_giveaways", description="Clean up old ended/cancelled giveaways (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(days_old="Remove giveaways older than this many days (default: 30)")
async def cleanup_giveaways(interaction: discord.Interaction, days_old: Optional[int] = 30):
    """Clean up old giveaways from the database (server-specific only)."""
    await interaction.response.defer(ephemeral=True)
    
    if days_old < 1 or days_old > 365:
        await interaction.followup.send("❌ Days must be between 1 and 365.", ephemeral=True)
        return
    
    # Confirmation
    embed = discord.Embed(
        title="⚠️ Confirm Cleanup",
        description=f"This will remove all ended/cancelled giveaways older than {days_old} days from **this server only**.\n\n"
                   f"**This action cannot be undone!**",
        color=discord.Color.orange()
    )
    
    view = ConfirmationView(interaction.user.id)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    
    await view.wait()
    if not view.confirmed:
        await interaction.edit_original_response(content="❌ Cleanup cancelled.", embed=None, view=None)
        return
    
    # Perform cleanup (server-specific only)
    cleanup_date = datetime.now(timezone.utc) - timedelta(days=days_old)
    server_id = interaction.guild.id
    cleaned_count = 0
    
    for message_id in list(giveaways.keys()):
        data = giveaways[message_id]
        if data.get("server_id") != server_id:
            continue
            
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
    
    if cleaned_count > 0:
        await save_database()
    
    await interaction.edit_original_response(
        content=f"✅ Cleanup complete! Removed {cleaned_count} old giveaways from this server.",
        embed=None,
        view=None
    )
    
    logging.info(f"Cleaned up {cleaned_count} old giveaways in {interaction.guild.name}")

# Get Discord token and start the bot
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is not set in the environment.")

# Start keep alive system and run the bot
keep_alive()
bot.run(DISCORD_TOKEN)
