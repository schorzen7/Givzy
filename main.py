import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
import asyncio
import os
import json
from datetime import datetime, timedelta, UTC
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}  # Ongoing giveaways
joined_users = {}  # Users who joined giveaways
role_rewards = {}  # {guild_id: {level: role_id}}
user_xp = {}  # {guild_id: {user_id: {"xp": int, "last_message": float}}}
data_file = "data.json"

def load_data():
    global role_rewards, user_xp
    if os.path.isfile(data_file):
        with open(data_file, "r") as f:
            data = json.load(f)
            role_rewards = data.get("role_rewards", {})
            user_xp = data.get("user_xp", {})

def save_data():
    with open(data_file, "w") as f:
        json.dump({
            "role_rewards": role_rewards,
            "user_xp": user_xp
        }, f, indent=4)

@bot.event
async def on_ready():
    keep_alive()
    await tree.sync()
    load_data()
    print(f"Logged in as {bot.user}")

def calculate_level(xp):
    return int(xp ** 0.5)

def get_progress_bar(level, xp):
    next_level = level + 1
    current = xp
    required = next_level ** 2
    percent = int((current / required) * 10)
    bar = "🟩" * percent + "⬜" * (10 - percent)
    return f"[{bar}] {current}/{required} XP"

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    guild_id = str(message.guild.id)
    user_id = str(message.author.id)
    now = datetime.now().timestamp()

    user_data = user_xp.setdefault(guild_id, {}).setdefault(user_id, {"xp": 0, "last_message": 0})
    if now - user_data["last_message"] >= 60:  # 1 minute cooldown
        user_data["xp"] += 5
        user_data["last_message"] = now
        level = calculate_level(user_data["xp"])

        if guild_id in role_rewards:
            for lvl, role_id in role_rewards[guild_id].items():
                if level >= int(lvl):
                    role = message.guild.get_role(int(role_id))
                    if role and role not in message.author.roles:
                        await message.author.add_roles(role)
                        await message.channel.send(f"{message.author.mention} has reached Level {lvl} and earned the role: {role.name}!")
    save_data()
    await bot.process_commands(message)

@tree.command(name="rank", description="Check your level and XP")
async def rank(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    user_id = str(interaction.user.id)
    user_data = user_xp.get(guild_id, {}).get(user_id, {"xp": 0})
    xp = user_data["xp"]
    level = calculate_level(xp)
    progress = get_progress_bar(level, xp)
    await interaction.response.send_message(
        f"📊 {interaction.user.mention}, you're currently **Level {level}** with **{xp} XP**!\n{progress}",
        ephemeral=True
    )

@tree.command(name="leaderboard", description="Show the top users by XP")
async def leaderboard(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    guild_data = user_xp.get(guild_id, {})
    sorted_users = sorted(guild_data.items(), key=lambda item: item[1]["xp"], reverse=True)[:10]
    embed = discord.Embed(title="🏆 XP Leaderboard", color=discord.Color.gold())

    for i, (user_id, data) in enumerate(sorted_users, start=1):
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"<@{user_id}>"
        level = calculate_level(data["xp"])
        embed.add_field(name=f"{i}. {name}", value=f"Level {level} - {data['xp']} XP", inline=False)

    await interaction.response.send_message(embed=embed)

@tree.command(name="addrank", description="Set a role reward for a specific level")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(role="The role to assign", level="The level required to get the role")
async def addrank(interaction: discord.Interaction, role: discord.Role, level: int):
    guild_id = str(interaction.guild.id)
    role_rewards.setdefault(guild_id, {})[str(level)] = role.id
    save_data()
    await interaction.response.send_message(f"🎖️ Users who reach Level {level} will now get the role {role.mention}!", ephemeral=True)

@tree.command(name="removerr", description="Remove a role reward from a level")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(level="The level of the role reward to remove")
async def removerr(interaction: discord.Interaction, level: int):
    guild_id = str(interaction.guild.id)
    if guild_id in role_rewards and str(level) in role_rewards[guild_id]:
        del role_rewards[guild_id][str(level)]
        save_data()
        await interaction.response.send_message(f"❌ Removed role reward for Level {level}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ No role reward found for Level {level}.", ephemeral=True)

@tree.command(name="daily", description="Claim daily bonus XP")
async def daily(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    user_id = str(interaction.user.id)
    user_data = user_xp.setdefault(guild_id, {}).setdefault(user_id, {"xp": 0, "last_message": 0, "last_daily": 0})
    now = datetime.now().timestamp()

    if now - user_data.get("last_daily", 0) >= 86400:
        user_data["xp"] += 20
        user_data["last_daily"] = now
        save_data()
        await interaction.response.send_message("✅ You claimed your daily 20 XP!", ephemeral=True)
    else:
        remaining = 86400 - (now - user_data.get("last_daily", 0))
        hours, rem = divmod(int(remaining), 3600)
        minutes, seconds = divmod(rem, 60)
        await interaction.response.send_message(
            f"🕒 You already claimed your daily XP. Try again in {hours}h {minutes}m {seconds}s.", ephemeral=True
        )

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(duration="Duration in seconds", prize="Prize name", donor="Your name", role="Optional role required to join")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway(interaction: discord.Interaction, duration: int, prize: str, donor: str, role: discord.Role = None):
    if interaction.channel_id in giveaways:
        await interaction.response.send_message("⚠️ A giveaway is already running in this channel.", ephemeral=True)
        return

    class GiveawayView(View):
        def __init__(self, timeout):
            super().__init__(timeout=timeout)
            self.message = None

        @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green)
        async def join(self, interaction2: discord.Interaction, button: Button):
            if role and role not in interaction2.user.roles:
                await interaction2.response.send_message(f"🚫 You need the {role.name} role to join.", ephemeral=True)
                return
            if interaction2.user.id in joined_users[interaction.channel_id]:
                await interaction2.response.send_message("⚠️ You've already joined!", ephemeral=True)
                return
            joined_users[interaction.channel_id].append(interaction2.user.id)
            await interaction2.response.send_message("🎉 Successfully joined the giveaway!", ephemeral=True)
            await self.update_embed()

        async def update_embed(self):
            embed = self.message.embeds[0]
            embed.set_footer(text=f"Participants: {len(joined_users[interaction.channel_id])}")
            await self.message.edit(embed=embed, view=self)

    end_time = datetime.now(UTC) + timedelta(seconds=duration)
    now = datetime.now(UTC)
    joined_users[interaction.channel_id] = []
    giveaways[interaction.channel_id] = True

    embed = discord.Embed(
        title="🎉 Giveaway Started!",
        description=f"Prize: **{prize}**\nDonor: **{donor}**\nEnds in **{duration} seconds**\nRequired Role: {role.mention if role else 'None'}",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Participants: 0")

    view = GiveawayView(timeout=duration)
    message = await interaction.channel.send(embed=embed, view=view)
    view.message = message
    await interaction.response.send_message("✅ Giveaway started!", ephemeral=True)

    while datetime.now(UTC) < end_time:
        await asyncio.sleep(1)
        await view.update_embed()

    await asyncio.sleep(1)
    await message.edit(view=None)

    entries = joined_users.get(interaction.channel_id, [])
    if entries:
        winner_id = random.choice(entries)
        winner = interaction.guild.get_member(winner_id)
        await interaction.channel.send(f"🎊 Congratulations {winner.mention}, you won the giveaway for **{prize}**!")
    else:
        await interaction.channel.send("😢 No one joined the giveaway.")

    del giveaways[interaction.channel_id]
    del joined_users[interaction.channel_id]

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ DISCORD_TOKEN environment variable is missing.")
bot.run(TOKEN)
