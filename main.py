import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button
import json
import random
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from typing import Optional
import pytz
import re
import logging
from keep_alive import keep_alive # Moved keep_alive import to the very top

# Configure logging (MUST come after all imports)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv() # MUST come after all imports and basic configurations

# Philippines timezone
PH_TZ = pytz.timezone('Asia/Manila')

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {} # Re-initialized global giveaways dictionary
user_cooldowns = {}
COOLDOWN_SECONDS = 30

# Load giveaways from JSON if exists
if os.path.exists("giveaways.json"):
    try:
        with open("giveaways.json", "r") as f:
            giveaways = json.load(f)
        logging.info(f"Loaded {len(giveaways)} giveaways from giveaways.json.")
    except json.JSONDecodeError:
        logging.error("Error reading giveaways.json, starting with empty giveaways.")
        giveaways = {}

def save_giveaways():
    """Saves the current giveaways data to giveaways.json."""
    with open("giveaways.json", "w") as f:
        json.dump(giveaways, f, indent=4)
    # logging.info("Giveaways data saved to giveaways.json.") # Uncomment for verbose logging


def format_time_left(end_time: datetime):
    """Formats the remaining time until the giveaway ends."""
    now = datetime.now(timezone.utc)
    remaining = end_time - now
    total_seconds = int(remaining.total_seconds())
    if total_seconds <= 0:
        return "0s"
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)

class JoinView(View):
    """
    A persistent view for joining giveaways.
    The timeout is set to None so it persists across bot restarts.
    """
    def __init__(self, message_id: str, end_time: datetime):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.end_time = end_time

    @property
    def custom_id(self):
        return f"giveaway_join_view:{self.message_id}"

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green, custom_id="join_button")
    async def join(self, interaction: discord.Interaction, button: Button):
        """Callback for the join button."""
        user_id = str(interaction.user.id)
        now = datetime.now(timezone.utc)

        # Cooldown check
        if user_id in user_cooldowns:
            diff = (now - user_cooldowns[user_id]).total_seconds()
            if diff < COOLDOWN_SECONDS:
                await interaction.response.send_message(
                    "Please be patient, you're in cooldown.",
                    ephemeral=True
                )
                return

        user_cooldowns[user_id] = now

        # Fetch giveaway data from the global dictionary
        giveaway_data = giveaways.get(self.message_id)

        if not giveaway_data:
            await interaction.response.send_message("❌ Giveaway not found or has ended.", ephemeral=True)
            return

        if giveaway_data.get("status") != "active":
            await interaction.response.send_message(f"❌ This giveaway is already {giveaway_data.get('status', 'not active')}.", ephemeral=True)
            return

        # Ensure participants list exists
        if "participants" not in giveaway_data:
            giveaway_data["participants"] = []

        if user_id in giveaway_data["participants"]:
            await interaction.response.send_message("❌ You already joined this giveaway!", ephemeral=True)
            return

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
        # Update participants in the global dictionary and save to JSON
        giveaways[self.message_id] = giveaway_data # Ensure the global dict is updated
        save_giveaways()
        await interaction.response.send_message("✅ You have joined the giveaway!", ephemeral=True)

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(prize="What is the prize?", winners="How many winners?", duration="Duration (e.g., 30s, 5m, 2h, 1d)", role="Optional role required to join")
async def giveaway(interaction: discord.Interaction, prize: str, winners: int, duration: str, role: Optional[discord.Role] = None):
    """Starts a new giveaway."""
    if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message("❌ Giveaways can only be started in text channels or threads!", ephemeral=True)
        return

    if interaction.guild is None:
        await interaction.response.send_message("❌ This command can only be used in a server!", ephemeral=True)
        return

    bot_perms = interaction.channel.permissions_for(interaction.guild.me)
    missing_perms = []

    if not bot_perms.send_messages:
        missing_perms.append("Send Messages")
    if not bot_perms.embed_links:
        missing_perms.append("Embed Links")
    if not bot_perms.read_message_history:
        missing_perms.append("Read Message History")
    if not bot_perms.manage_messages:
        missing_perms.append("Manage Messages")

    if missing_perms:
        await interaction.response.send_message(
            f"❌ I'm missing these permissions in this channel: **{', '.join(missing_perms)}**\n"
            f"Please give me these permissions and try again.",
            ephemeral=True
        )
        return

    total_seconds = 0
    duration_match = re.fullmatch(r'(\d+)([smhd])', duration.lower())

    if duration_match:
        value = int(duration_match.group(1))
        unit = duration_match.group(2)

        if unit == 's':
            total_seconds = value
        elif unit == 'm':
            total_seconds = value * 60
        elif unit == 'h':
            total_seconds = value * 3600
        elif unit == 'd':
            total_seconds = value * 86400
    else:
        await interaction.response.send_message(
            "❌ Invalid duration format. Please use formats like `30s`, `5m`, `2h`, or `1d`.",
            ephemeral=True
        )
        return

    if total_seconds <= 0:
        await interaction.response.send_message("❌ Duration must be a positive value.", ephemeral=True)
        return

    end_time = datetime.now(timezone.utc) + timedelta(seconds=total_seconds)
    end_timestamp = int(end_time.timestamp())

    description_parts = [
        f"🎁 **Prize:** {prize}",
        f"✨ **Donor:** {interaction.user.mention}",
        f"⏰ **Ends:** <t:{end_timestamp}:F>",
        f"🏆 **Winners:** {winners}"
    ]

    if role is not None:
        description_parts.append(f"🛡️ **Required Role:** {role.mention}")

    embed = discord.Embed(
        title="🎉✨ GIVEAWAY! ✨🎉",
        description="\n".join(description_parts),
        color=discord.Color.from_rgb(255, 105, 180)
    )
    embed.set_footer(text="Click the 🎉 button to enter!")

    view = JoinView(message_id="temp_placeholder", end_time=end_time)

    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()

    message_id_str = str(message.id)
    message_id_int = message.id

    view.message_id = message_id_str
    bot.add_view(view, message_id=message_id_int)

    # Store giveaway data in the global dictionary and save to JSON
    giveaways[message_id_str] = {
        "channel_id": interaction.channel.id,
        "end_time": end_time.isoformat(),
        "prize": prize,
        "winners": winners,
        "participants": [],
        "donor": interaction.user.id,
        "required_role": role.id if role is not None else None,
        "status": "active"
    }
    save_giveaways()


@tree.command(name="reroll", description="Reroll winners for an ended giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(message_id="The message ID of the ended giveaway.")
async def reroll(interaction: discord.Interaction, message_id: str):
    """Rerolls winners for a specified ended giveaway."""
    await interaction.response.defer(ephemeral=True)

    # Fetch giveaway data from the global dictionary
    giveaway_data = giveaways.get(message_id)

    if not giveaway_data:
        await interaction.followup.send("❌ Giveaway not found. Please ensure you provide the correct message ID.", ephemeral=True)
        return

    if giveaway_data.get("status") != "ended":
        await interaction.followup.send(f"❌ This giveaway is currently '{giveaway_data.get('status', 'active')}' and cannot be rerolled. Only ended giveaways can be rerolled.", ephemeral=True)
        return

    participants = giveaway_data.get("participants", [])
    if not participants:
        await interaction.followup.send("❌ No one participated in this giveaway, so no winners can be rerolled.", ephemeral=True)
        return

    channel = bot.get_channel(giveaway_data["channel_id"])
    if not channel or not isinstance(channel, (discord.TextChannel, discord.Thread)):
        await interaction.followup.send("❌ The channel for this giveaway could not be found or is not a text channel/thread.", ephemeral=True)
        return

    try:
        original_message = await channel.fetch_message(int(message_id))
    except discord.NotFound:
        await interaction.followup.send("❌ The original giveaway message could not be found. It might have been deleted.", ephemeral=True)
        return
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to access the original giveaway message.", ephemeral=True)
        return
    except Exception as e:
        await interaction.followup.send(f"An unexpected error occurred while fetching the message: {e}", ephemeral=True)
        return

    winners_count = giveaway_data["winners"]
    new_winner_ids = random.sample(participants, min(len(participants), winners_count))
    new_mentions = " ".join(f"<@{uid}>" for uid in new_winner_ids)

    reroll_embed = discord.Embed(
        title="🔄 Giveaway Reroll!",
        description=f"New winners for **{giveaway_data['prize']}**!\n"
                    f"Congratulations {new_mentions}!",
        color=discord.Color.gold()
    )
    reroll_embed.set_footer(text=f"Rerolled by {interaction.user.display_name}")

    await original_message.reply(embed=reroll_embed)
    await interaction.followup.send(f"✅ Successfully rerolled winners for giveaway ID: `{message_id}`", ephemeral=True)


@tree.command(name="cancelgiveaway", description="Cancel an active giveaway.")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(message_id="The message ID of the giveaway to cancel.")
async def cancel_giveaway(interaction: discord.Interaction, message_id: str):
    """Cancels a specified active giveaway."""
    await interaction.response.defer(ephemeral=True)

    # Fetch giveaway data from the global dictionary
    giveaway_data = giveaways.get(message_id)

    if not giveaway_data:
        await interaction.followup.send("❌ Giveaway not found. Please ensure you provide the correct message ID.", ephemeral=True)
        return

    if giveaway_data.get("status") != "active":
        await interaction.followup.send(f"❌ This giveaway is already '{giveaway_data.get('status', 'not active')}' and cannot be cancelled.", ephemeral=True)
        return

    channel = bot.get_channel(giveaway_data["channel_id"])
    if not channel or not isinstance(channel, (discord.TextChannel, discord.Thread)):
        await interaction.followup.send("❌ The channel for this giveaway could not be found or is not a text channel/thread.", ephemeral=True)
        return

    try:
        original_message = await channel.fetch_message(int(message_id))
    except discord.NotFound:
        await interaction.followup.send("❌ The original giveaway message could not be found. It might have been deleted.", ephemeral=True)
        # If message is gone, just update status in global dict and save
        giveaway_data["status"] = "cancelled"
        giveaways[message_id] = giveaway_data
        save_giveaways()
        return
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to access or edit the original giveaway message.", ephemeral=True)
        return
    except Exception as e:
        await interaction.followup.send(f"An unexpected error occurred while fetching the message: {e}", ephemeral=True)
        return

    # Update giveaway status in global dictionary and save
    giveaway_data["status"] = "cancelled"
    giveaways[message_id] = giveaway_data
    save_giveaways()

    # Edit the original message
    cancelled_embed = discord.Embed(
        title="🚫 GIVEAWAY CANCELLED 🚫",
        description=f"The giveaway for **{giveaway_data['prize']}** has been cancelled by {interaction.user.mention}.",
        color=discord.Color.red()
    )
    cancelled_embed.set_footer(text="This giveaway has been cancelled.")

    await original_message.edit(embed=cancelled_embed, view=None)

    await interaction.followup.send(f"✅ Successfully cancelled giveaway ID: `{message_id}`", ephemeral=True)


@bot.event
async def on_ready():
    """Event handler for when the bot is ready."""
    logging.info(f"Logged in as {bot.user}")
    try:
        synced = await tree.sync()
        logging.info(f"Synced {len(synced)} commands.")
    except Exception as e:
        logging.error(f"Failed to sync commands: {e}")

    # --- Persistent View Re-attachment & Startup Catch-up (using JSON) ---
    bot.add_view(JoinView(message_id="dummy", end_time=datetime.now(timezone.utc)))
    logging.info("Registered JoinView for persistence.")

    # Load all giveaways from JSON on startup
    global giveaways # Ensure we are modifying the global dictionary
    if os.path.exists("giveaways.json"):
        try:
            with open("giveaways.json", "r") as f:
                giveaways = json.load(f)
            logging.info(f"Loaded {len(giveaways)} giveaways from giveaways.json on startup.")
        except json.JSONDecodeError:
            logging.error("Error reading giveaways.json on startup, starting with empty giveaways.")
            giveaways = {}

    active_giveaways_on_startup = []
    # Iterate over a copy of items to allow modification of the original dictionary
    for message_id, data in list(giveaways.items()):
        end_time = datetime.fromisoformat(data["end_time"])

        if data.get("status") == "active":
            if datetime.now(timezone.utc) >= end_time:
                # Giveaway expired while bot was offline, mark as ended
                data["status"] = "ended"
                giveaways[message_id] = data # Update in global dict
                save_giveaways() # Save immediately
                logging.info(f"Giveaway {message_id} found as active but expired on startup. Marking as 'ended'.")
                continue

            channel_id = data["channel_id"]
            channel = bot.get_channel(channel_id)
            if channel:
                if isinstance(channel, (discord.TextChannel, discord.Thread)):
                    try:
                        await channel.fetch_message(int(message_id))
                        bot.add_view(JoinView(message_id=message_id, end_time=end_time), message_id=int(message_id))
                        active_giveaways_on_startup.append(message_id)
                        logging.info(f"Re-attached JoinView for message {message_id} in channel {channel_id}")
                    except discord.NotFound:
                        logging.warning(f"Giveaway message {message_id} not found in channel {channel_id}. Marking as ended.")
                        data["status"] = "ended"
                        giveaways[message_id] = data
                        save_giveaways()
                    except discord.Forbidden:
                        logging.warning(f"Missing permissions to fetch message {message_id} in channel {channel_id}. Marking as ended.")
                        data["status"] = "ended"
                        giveaways[message_id] = data
                        save_giveaways()
                    except Exception as e:
                        logging.error(f"Error re-attaching view for message {message_id}: {e}")
                else:
                    logging.warning(f"Channel {channel_id} is not a text channel or thread for giveaway message {message_id}. Marking as ended.")
                    data["status"] = "ended"
                    giveaways[message_id] = data
                    save_giveaways()
            else:
                logging.warning(f"Channel {channel_id} not found for giveaway message {message_id}. Marking as ended.")
                data["status"] = "ended"
                giveaways[message_id] = data
                save_giveaways()
    logging.info(f"Re-attached views for {len(active_giveaways_on_startup)} active giveaways on startup.")
    # --- End Persistent View Re-attachment ---

    check_giveaways.start()
    logging.info("check_giveaways task started.")

@tasks.loop(seconds=30)
async def check_giveaways():
    """Background task to check and update/end giveaways."""
    logging.info(f"[{datetime.now(timezone.utc).isoformat()}] Running check_giveaways task.")
    now = datetime.now(timezone.utc)

    # Use a copy of the global giveaways dictionary for iteration
    # This prevents issues if the dictionary is modified during iteration
    for message_id, data in list(giveaways.items()):
        if data.get("status") != "active":
            continue

        end_time = datetime.fromisoformat(data["end_time"])
        channel = bot.get_channel(data["channel_id"])

        if not channel:
            logging.warning(f"[{datetime.now(timezone.utc).isoformat()}] Channel {data['channel_id']} not found for giveaway {message_id}. Marking as ended.")
            giveaways[message_id]["status"] = "ended" # Update the global dict
            save_giveaways()
            continue

        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            try:
                message = await channel.fetch_message(int(message_id))

                if now >= end_time:
                    logging.info(f"[{datetime.now(timezone.utc).isoformat()}] Giveaway {message_id} has ended. Processing winners.")
                    participants = data.get("participants", [])
                    if len(participants) == 0:
                        await message.reply("❌ Giveaway ended. No one joined.")
                        logging.info(f"[{datetime.now(timezone.utc).isoformat()}] Giveaway {message_id}: No participants.")
                    else:
                        winner_ids = random.sample(participants, min(len(participants), data["winners"]))
                        mentions = " ".join(f"<@{uid}>" for uid in winner_ids)
                        await message.reply(f"🎉 Giveaway ended! Congrats {mentions}!\nPrize: **{data['prize']}**")
                        logging.info(f"[{datetime.now(timezone.utc).isoformat()}] Giveaway {message_id}: Winners announced: {mentions}")

                    giveaways[message_id]["status"] = "ended" # Mark as ended in global dict
                    save_giveaways() # Save immediately
                    ended_embed = message.embeds[0] if message.embeds else discord.Embed()
                    ended_embed.title = "🎉 GIVEAWAY ENDED! 🎉"
                    ended_embed.color = discord.Color.greyple()
                    await message.edit(embed=ended_embed, view=None)
                    logging.info(f"[{datetime.now(timezone.utc).isoformat()}] Giveaway {message_id}: Message updated and buttons disabled.")
                else:
                    end_timestamp = int(end_time.timestamp())
                    description_parts = [
                        f"🎁 **Prize:** {data['prize']}",
                        f"✨ **Donor:** <@{data['donor']}>",
                        f"⏰ **Ends:** <t:{end_timestamp}:F>",
                        f"🏆 **Winners:** {data['winners']}"
                    ]

                    if data.get('required_role'):
                        description_parts.append(f"🛡️ **Required Role:** <@&{data['required_role']}>")

                    embed = discord.Embed(
                        title="🎉✨ GIVEAWAY! ✨🎉",
                        description="\n".join(description_parts),
                        color=discord.Color.from_rgb(255, 105, 180)
                    )
                    embed.set_footer(text="Click the 🎉 button to enter!")

                    await message.edit(embed=embed)
            except discord.Forbidden:
                logging.warning(f"[{datetime.now(timezone.utc).isoformat()}] Missing permissions to manage message {message_id} in {channel.name}. Marking as ended.")
                giveaways[message_id]["status"] = "ended"
                save_giveaways()
            except discord.NotFound:
                logging.warning(f"[{datetime.now(timezone.utc).isoformat()}] Giveaway message {message_id} was deleted in {channel.name}. Marking as ended.")
                giveaways[message_id]["status"] = "ended"
                save_giveaways()
            except Exception as e:
                logging.error(f"[{datetime.now(timezone.utc).isoformat()}] Error processing giveaway {message_id}: {e}")
        else:
            logging.warning(f"[{datetime.now(timezone.utc).isoformat()}] Channel {channel.id} is not a text channel or thread for giveaway {message_id}. Marking as ended.")
            giveaways[message_id]["status"] = "ended"
            save_giveaways()


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is not set in the environment.")

keep_alive()

bot.run(DISCORD_TOKEN)
