import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
from dotenv import load_dotenv
import json
import datetime

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = app_commands.CommandTree(bot)

giveaways = []
cooldowns = {}

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    check_giveaway_end.start()
    await tree.sync()

# Helper: Format timestamp
def format_timestamp(dt):
    return f"<t:{int(dt.timestamp())}:F>"

# Slash Command
@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    duration="Duration (in seconds)",
    prize="What is the prize?",
    role="(Optional) Role required to join",
)
async def giveaway(interaction: discord.Interaction, duration: int, prize: str, role: discord.Role = None):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You need Manage Server permission.", ephemeral=True)
        return

    end_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=duration)
    donor = interaction.user.mention
    role_req = f"{role.mention}" if role else "None"
    embed = discord.Embed(title="🎉 Giveaway Started!", color=discord.Color.purple())
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Ends At", value=format_timestamp(end_time), inline=True)
    embed.add_field(name="Donor", value=donor, inline=True)
    embed.add_field(name="Role Requirement", value=role_req, inline=True)
    embed.set_footer(text="Click the button below to join!")
    view = GiveawayView(prize, end_time, interaction.channel.id, role.id if role else None)
    message = await interaction.channel.send(embed=embed, view=view)

    giveaways.append({
        "message_id": message.id,
        "channel_id": interaction.channel.id,
        "end_time": end_time.timestamp(),
        "prize": prize,
        "donor": donor,
        "participants": [],
        "role_id": role.id if role else None
    })

    await interaction.response.send_message("Giveaway started!", ephemeral=True)

class GiveawayView(discord.ui.View):
    def __init__(self, prize, end_time, channel_id, role_id):
        super().__init__(timeout=None)
        self.prize = prize
        self.end_time = end_time
        self.channel_id = channel_id
        self.role_id = role_id

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        now = datetime.datetime.utcnow().timestamp()
        user_id = str(interaction.user.id)

        if user_id in cooldowns and now - cooldowns[user_id] < 10:
            await interaction.response.send_message("🕐 Please wait 10 seconds before clicking again!", ephemeral=True)
            return
        cooldowns[user_id] = now

        for g in giveaways:
            if g["message_id"] == interaction.message.id:
                if g["role_id"]:
                    role = interaction.guild.get_role(g["role_id"])
                    if role not in interaction.user.roles:
                        await interaction.response.send_message(f"You need the {role.mention} role to join!", ephemeral=True)
                        return
                if user_id in g["participants"]:
                    await interaction.response.send_message("You already joined!", ephemeral=True)
                else:
                    g["participants"].append(user_id)
                    await interaction.response.send_message("You're in the giveaway!", ephemeral=True)
                return

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("You don't have permission to cancel.", ephemeral=True)
            return
        for g in giveaways:
            if g["message_id"] == interaction.message.id:
                giveaways.remove(g)
                await interaction.message.edit(content="❌ Giveaway Cancelled.", view=None)
                await interaction.response.send_message("Giveaway cancelled.", ephemeral=True)
                return

    @discord.ui.button(label="🔄 Reroll", style=discord.ButtonStyle.blurple)
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("You don't have permission to reroll.", ephemeral=True)
            return
        for g in giveaways:
            if g["message_id"] == interaction.message.id:
                if not g["participants"]:
                    await interaction.response.send_message("No participants to reroll.", ephemeral=True)
                    return
                winner_id = int(random.choice(g["participants"]))
                winner = interaction.guild.get_member(winner_id)
                await interaction.channel.send(f"🎊 New winner for **{g['prize']}**: {winner.mention}!")
                await interaction.response.send_message("Rerolled!", ephemeral=True)
                return

@tasks.loop(seconds=120)
async def check_giveaway_end():
    now = datetime.datetime.utcnow().timestamp()
    for g in giveaways[:]:
        if now >= g["end_time"]:
            channel = bot.get_channel(g["channel_id"])
            if not channel:
                giveaways.remove(g)
                continue
            try:
                message = await channel.fetch_message(g["message_id"])
                if not g["participants"]:
                    await channel.send(f"❌ No one joined the giveaway for **{g['prize']}**.")
                else:
                    winner_id = int(random.choice(g["participants"]))
                    winner = channel.guild.get_member(winner_id)
                    await channel.send(f"🎉 Congrats {winner.mention}! You won **{g['prize']}**!")
                await message.edit(view=None)
            except:
                pass
            giveaways.remove(g)

bot.run(TOKEN)
