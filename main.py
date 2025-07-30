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
from keep_alive import keep_alive  # Import keep alive

load_dotenv()

# Philippines timezone
PH_TZ = pytz.timezone('Asia/Manila')

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}
user_cooldowns = {}
COOLDOWN_SECONDS = 30

# Load giveaways from JSON if exists
if os.path.exists("giveaways.json"):
    with open("giveaways.json", "r") as f:
        giveaways = json.load(f)

def save_giveaways():
    with open("giveaways.json", "w") as f:
        json.dump(giveaways, f, indent=4)

def format_time_left(end_time: datetime):
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
    def __init__(self, message_id, end_time):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.end_time = end_time

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green, custom_id="join_button")
    async def join(self, interaction: discord.Interaction, button: Button):
        user_id = str(interaction.user.id)
        now = datetime.now(timezone.utc)

        if user_id in user_cooldowns:
            diff = (now - user_cooldowns[user_id]).total_seconds()
            if diff < COOLDOWN_SECONDS:
                # Calculate when they can try again
                can_try_again_utc = user_cooldowns[user_id] + timedelta(seconds=COOLDOWN_SECONDS)
                can_try_again_ph = can_try_again_utc.astimezone(PH_TZ)

                # Format Philippines time
                ph_time_str = can_try_again_ph.strftime("%B %d, %Y at %I:%M:%S %p")
                timestamp = int(can_try_again_utc.timestamp())

                await interaction.response.send_message(
                    f"🕒 **Cooldown Active!**\n"
                    f"⏰ Wait {int(COOLDOWN_SECONDS - diff)} more seconds\n"
                    f"🇵🇭 **Philippines Time:** {ph_time_str}\n"
                    f"🌍 **Your Time:** <t:{timestamp}:F>\n"
                    f"⏳ **Available:** <t:{timestamp}:R>", 
                    ephemeral=True
                )
                return

        user_cooldowns[user_id] = now

        giveaway_data = giveaways.get(self.message_id)
        if not giveaway_data:
            await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
            return

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
        save_giveaways()
        await interaction.response.send_message("✅ You have joined the giveaway!", ephemeral=True)

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(prize="What is the prize?", winners="How many winners?", duration="Duration in seconds", role="Optional role required to join")
async def giveaway(interaction: discord.Interaction, prize: str, winners: int, duration: int, role: Optional[discord.Role] = None):
    # Type check the interaction channel
    if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message("❌ Giveaways can only be started in text channels!", ephemeral=True)
        return

    # Check bot permissions in this channel
    bot_perms = interaction.channel.permissions_for(interaction.guild.me)
    missing_perms = []

    if not bot_perms.send_messages:
        missing_perms.append("Send Messages")
    if not bot_perms.embed_links:
        missing_perms.append("Embed Links")
    if not bot_perms.read_message_history:
        missing_perms.append("Read Message History")

    if missing_perms:
        await interaction.response.send_message(
            f"❌ I'm missing these permissions in this channel: **{', '.join(missing_perms)}**\n"
            f"Please give me these permissions and try again.",
            ephemeral=True
        )
        return

    end_time = datetime.now(timezone.utc) + timedelta(seconds=duration)

    # Build description with proper None handling
    description_parts = [
        f"**Prize:** {prize}",
        f"**Donor:** {interaction.user.mention}",
        f"**Ends in:** {format_time_left(end_time)}",
        f"**Winners:** {winners}"
    ]

    if role is not None:
        description_parts.append(f"**Required Role:** {role.mention}")

    embed = discord.Embed(
        title="🎉 Giveaway Started!",
        description="\n".join(description_parts),
        color=discord.Color.blue()
    )
    embed.set_footer(text="Click the 🎉 button to enter!")

    view = JoinView(message_id="temp", end_time=end_time)

    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()

    message_id = str(message.id)
    view.message_id = message_id

    giveaways[message_id] = {
        "channel_id": interaction.channel.id,
        "end_time": end_time.isoformat(),
        "prize": prize,
        "winners": winners,
        "participants": [],
        "donor": interaction.user.id,
        "required_role": role.id if role is not None else None
    }
    save_giveaways()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    check_giveaways.start()

@tasks.loop(seconds=30)  # Reduced frequency to save API calls
async def check_giveaways():
    now = datetime.now(timezone.utc)
    for message_id, data in list(giveaways.items()):
        end_time = datetime.fromisoformat(data["end_time"])
        if now >= end_time:
            # Handle ended giveaways
            channel = bot.get_channel(data["channel_id"])
            if isinstance(channel, discord.TextChannel):
                try:
                    message = await channel.fetch_message(int(message_id))
                    participants = data["participants"]
                    if len(participants) == 0:
                        await message.reply("❌ Giveaway ended. No one joined.")
                    else:
                        winner_ids = random.sample(participants, min(len(participants), data["winners"]))
                        mentions = " ".join(f"<@{uid}>" for uid in winner_ids)
                        await message.reply(f"🎉 Giveaway ended! Congrats {mentions}!\nPrize: **{data['prize']}**")
                except discord.Forbidden:
                    print(f"Missing permissions to announce giveaway in {channel.name}. Please check bot permissions.")
                except discord.NotFound:
                    print(f"Giveaway message {message_id} was deleted.")
                except Exception as e:
                    print(f"Error announcing giveaway: {e}")
            giveaways.pop(message_id)
            save_giveaways()
        else:
            # Update ongoing giveaways (less frequently)
            channel = bot.get_channel(data["channel_id"])
            if isinstance(channel, discord.TextChannel):
                try:
                    message = await channel.fetch_message(int(message_id))

                    # Rebuild the embed description
                    description_parts = [
                        f"**Prize:** {data['prize']}",
                        f"**Donor:** <@{data['donor']}>",
                        f"**Ends in:** {format_time_left(end_time)}",
                        f"**Winners:** {data['winners']}"
                    ]

                    if data.get('required_role'):
                        description_parts.append(f"**Required Role:** <@&{data['required_role']}>")

                    embed = discord.Embed(
                        title="🎉 Giveaway Started!",
                        description="\n".join(description_parts),
                        color=discord.Color.blue()
                    )
                    embed.set_footer(text="Click the 🎉 button to enter!")

                    await message.edit(embed=embed)
                except discord.Forbidden:
                    print(f"Missing permissions to edit message in {channel.name}. Please check bot permissions.")
                except discord.NotFound:
                    print(f"Giveaway message {message_id} was deleted.")
                except Exception as e:
                    print(f"Error updating message: {e}")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is not set in the environment.")

# Start keep alive server
keep_alive()

bot.run(DISCORD_TOKEN)
