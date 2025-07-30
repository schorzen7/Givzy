import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta, timezone
import asyncio
import os
import random
from keep_alive import keep_alive
from typing import Optional

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

class GivzyBot(commands.Bot):
    async def setup_hook(self):
        await self.tree.sync()
        self.loop.create_task(check_giveaways())

bot = GivzyBot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}
join_cooldowns = {}

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    prize="What is the giveaway prize?",
    winners="How many winners?",
    duration="Duration (e.g. 30s, 10m, 2h, 1d)",
    role="Optional role required to join"
)
async def giveaway(
    interaction: discord.Interaction,
    prize: str,
    winners: int,
    duration: str,
    role: Optional[discord.Role] = None
):
    member = interaction.user
    if not isinstance(member, discord.Member) or not member.guild_permissions.manage_messages:
        await interaction.response.send_message("You need Manage Messages permission to start a giveaway.", ephemeral=True)
        return

    seconds = convert_duration(duration)
    if seconds is None:
        await interaction.response.send_message("Invalid duration format. Use s, m, h, or d (e.g. 30s, 10m, 2h, 1d).", ephemeral=True)
        return

    end_time = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    timestamp = f"<t:{int(end_time.timestamp())}:f>"

    embed = discord.Embed(title="🎉 Giveaway Started!", color=discord.Color.purple())
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Ends At", value=timestamp, inline=False)
    embed.add_field(name="Winners", value=str(winners), inline=False)
    if role:
        embed.add_field(name="Required Role", value=role.mention, inline=False)

    join_button = discord.ui.Button(label="🎉 Join", style=discord.ButtonStyle.success, custom_id="join")
    cancel_button = discord.ui.Button(label="❌ Cancel", style=discord.ButtonStyle.danger, custom_id="cancel")
    reroll_button = discord.ui.Button(label="🔁 Reroll", style=discord.ButtonStyle.primary, custom_id="reroll")

    view = discord.ui.View()
    view.add_item(join_button)
    view.add_item(cancel_button)
    view.add_item(reroll_button)

    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()

    giveaways[message.id] = {
        "prize": prize,
        "end_time": end_time,
        "participants": set(),
        "message": message,
        "channel": message.channel,
        "ended": False,
        "role": role,
        "winners": winners
    }

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return

    msg = interaction.message
    if not msg or msg.id not in giveaways:
        return

    data = giveaways[msg.id]
    user = interaction.user
    if not isinstance(user, discord.Member):
        await interaction.response.send_message("Only server members can interact.", ephemeral=True)
        return

    custom_id = interaction.data.get("custom_id") if isinstance(interaction.data, dict) else None
    if not custom_id:
        return

    if custom_id == "join":
        now = datetime.now().timestamp()
        cooldown_expiry = join_cooldowns.get(user.id, 0)

        if now < cooldown_expiry:
            remaining = int(cooldown_expiry - now)
            await interaction.response.send_message(f"⏳ You're on cooldown! Try again in {remaining} seconds.", ephemeral=True)
            return

        join_cooldowns[user.id] = now + 30  # 30-second global cooldown

        if data["role"] and data["role"] not in user.roles:
            await interaction.response.send_message("You don't have the required role to join.", ephemeral=True)
            return
        if user.id in data["participants"]:
            await interaction.response.send_message("❗ You already joined this giveaway.", ephemeral=True)
            return

        data["participants"].add(user.id)
        await interaction.response.send_message("✅ You have joined the giveaway!", ephemeral=True)

    elif custom_id == "cancel":
        if not user.guild_permissions.manage_messages:
            await interaction.response.send_message("Only admins can cancel this giveaway.", ephemeral=True)
            return
        data["ended"] = True
        await msg.edit(content="🚫 This giveaway has been cancelled.", view=None)
        del giveaways[msg.id]
        await interaction.response.send_message("Giveaway cancelled.", ephemeral=True)

    elif custom_id == "reroll":
        if not user.guild_permissions.manage_messages:
            await interaction.response.send_message("Only admins can reroll.", ephemeral=True)
            return
        if not data["participants"]:
            await interaction.response.send_message("No participants to reroll.", ephemeral=True)
            return
        winner_id = random.choice(list(data["participants"]))
        winner = await bot.fetch_user(winner_id)
        await msg.channel.send(f"🎉 New winner for **{data['prize']}**: {winner.mention}")
        await interaction.response.send_message("✅ Rerolled the giveaway!", ephemeral=True)

async def check_giveaways():
    while True:
        now = datetime.now(timezone.utc)
        to_remove = []
        for gid, data in giveaways.items():
            if not data["ended"] and now >= data["end_time"]:
                data["ended"] = True
                winners = random.sample(list(data["participants"]), min(data["winners"], len(data["participants"])))
                if winners:
                    mentions = ", ".join(f"<@{uid}>" for uid in winners)
                    await data["channel"].send(f"🎉 Congratulations {mentions}! You won **{data['prize']}**!")
                else:
                    await data["channel"].send("❌ No one joined the giveaway.")
                await data["message"].edit(view=None)
                to_remove.append(gid)
        for gid in to_remove:
            del giveaways[gid]
        await asyncio.sleep(1)

def convert_duration(duration: str):
    try:
        unit = duration[-1]
        amount = int(duration[:-1])
        return {
            "s": amount,
            "m": amount * 60,
            "h": amount * 3600,
            "d": amount * 86400
        }.get(unit)
    except Exception:
        return None

# === KEEP ALIVE ===
keep_alive()

# === RUN ===
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN not set in environment variables.")
bot.run(TOKEN)
