import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import json
import os
import random
from datetime import datetime, timedelta
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

GIVEAWAY_FILE = "giveaways.json"
giveaways = {}

def load_giveaways():
    global giveaways
    if os.path.exists(GIVEAWAY_FILE):
        with open(GIVEAWAY_FILE, "r") as f:
            giveaways = json.load(f)

def save_giveaways():
    with open(GIVEAWAY_FILE, "w") as f:
        json.dump(giveaways, f, indent=4)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    check_giveaways.start()
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(f"Sync failed: {e}")

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(
    prize="What is the prize?",
    duration="How long? (e.g., 1h, 30m, 2d)",
    donor="Who is donating the prize?",
    role="Optional role required to join"
)
async def giveaway(
    interaction: discord.Interaction,
    prize: str,
    duration: str,
    donor: str,
    role: discord.Role = None
):
    await interaction.response.defer()

    seconds = parse_duration(duration)
    if seconds is None:
        await interaction.followup.send("Invalid duration format. Use `30m`, `2h`, `1d`, etc.", ephemeral=True)
        return

    end_time = datetime.utcnow() + timedelta(seconds=seconds)
    embed = discord.Embed(
        title="🎉 New Giveaway!",
        description=f"**Prize:** {prize}\n**Ends at:** <t:{int(end_time.timestamp())}:F>\n**Donor:** {donor}",
        color=discord.Color.green()
    )
    if role:
        embed.add_field(name="Role Required", value=role.mention)

    embed.set_footer(text="Click the button below to join!")

    join_button = discord.ui.Button(label="Join Giveaway", style=discord.ButtonStyle.success, custom_id="join")
    cancel_button = discord.ui.Button(label="Cancel Giveaway", style=discord.ButtonStyle.danger, custom_id="cancel")

    view = discord.ui.View(timeout=None)
    view.add_item(join_button)
    view.add_item(cancel_button)

    message = await interaction.followup.send(embed=embed, view=view)
    giveaways[str(message.id)] = {
        "prize": prize,
        "end_time": end_time.timestamp(),
        "donor": donor,
        "channel_id": message.channel.id,
        "message_id": message.id,
        "participants": [],
        "role_id": role.id if role else None,
        "ended": False
    }
    save_giveaways()

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data["custom_id"]
        message_id = str(interaction.message.id)
        user_id = str(interaction.user.id)

        if message_id not in giveaways:
            await interaction.response.send_message("This giveaway no longer exists.", ephemeral=True)
            return

        giveaway = giveaways[message_id]

        if custom_id == "join":
            if user_id in giveaway["participants"]:
                await interaction.response.send_message("You've already joined!", ephemeral=True)
            else:
                if giveaway["role_id"]:
                    role = interaction.guild.get_role(giveaway["role_id"])
                    if role not in interaction.user.roles:
                        await interaction.response.send_message("You don't have the required role to join.", ephemeral=True)
                        return
                giveaway["participants"].append(user_id)
                save_giveaways()
                await interaction.response.send_message("You have joined the giveaway!", ephemeral=True)

        elif custom_id == "cancel":
            if interaction.user.guild_permissions.manage_messages:
                giveaway["ended"] = True
                save_giveaways()
                await interaction.message.edit(content="❌ Giveaway has been cancelled.", embed=None, view=None)
                await interaction.response.send_message("Giveaway cancelled.", ephemeral=True)
            else:
                await interaction.response.send_message("You don't have permission to cancel.", ephemeral=True)

@tasks.loop(seconds=120)
async def check_giveaways():
    now = datetime.utcnow().timestamp()
    ended = []
    for msg_id, g in giveaways.items():
        if not g["ended"] and now >= g["end_time"]:
            ended.append(msg_id)

    for msg_id in ended:
        g = giveaways[msg_id]
        g["ended"] = True
        save_giveaways()

        channel = bot.get_channel(g["channel_id"])
        if not channel:
            continue

        try:
            message = await channel.fetch_message(g["message_id"])
        except discord.NotFound:
            continue

        if g["participants"]:
            winner_id = random.choice(g["participants"])
            winner = channel.guild.get_member(int(winner_id))
            winner_mention = winner.mention if winner else f"<@{winner_id}>"
            result_text = f"🎉 Congrats {winner_mention}! You won **{g['prize']}**! Donated by {g['donor']}."
        else:
            result_text = f"😢 No one joined the giveaway for **{g['prize']}**."

        await channel.send(result_text)
        await message.edit(content="🎉 Giveaway Ended", view=None)

def parse_duration(duration_str):
    try:
        duration_str = duration_str.lower().strip()
        num = int(''.join(filter(str.isdigit, duration_str)))
        if "s" in duration_str:
            return num
        elif "m" in duration_str:
            return num * 60
        elif "h" in duration_str:
            return num * 3600
        elif "d" in duration_str:
            return num * 86400
        return None
    except:
        return None

@tree.error
async def on_app_command_error(interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("You need `Manage Messages` permission to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message(f"An error occurred: {error}", ephemeral=True)

# === KEEP ALIVE ===
keep_alive()

# === START BOT ===
bot.run(os.getenv("DISCORD_TOKEN"))
