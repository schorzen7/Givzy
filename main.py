import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
from dotenv import load_dotenv
from keep_alive import keep_alive
from datetime import datetime, timedelta, UTC
import random

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(e)

def format_time(dt):
    return f"<t:{int(dt.timestamp())}:F>"

def format_duration(seconds):
    return f"<t:{int(datetime.now(UTC).timestamp()) + seconds}:R>"

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    prize="What is the prize?",
    duration="How long the giveaway lasts (in seconds)",
    donor="Who donated the prize?",
    role="Optional role required to join"
)
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str, role: discord.Role = None):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("You need the 'Manage Messages' permission to use this command.", ephemeral=True)
        return

    if duration < 30:
        await interaction.response.send_message("Giveaway duration must be at least 30 seconds.", ephemeral=True)
        return

    end_time = datetime.now(UTC) + timedelta(seconds=duration)
    embed = discord.Embed(title="🎉 Giveaway!", description=f"**Prize:** {prize}", color=discord.Color.gold())
    embed.add_field(name="Ends", value=format_time(end_time), inline=False)
    embed.add_field(name="Donor", value=donor, inline=False)
    if role:
        embed.add_field(name="Role Required", value=role.mention, inline=False)
    embed.set_footer(text="Click the button below to enter!")
    view = JoinButtonView(interaction.channel.id, prize, donor, role, end_time)
    message = await interaction.channel.send(embed=embed, view=view)
    giveaways[message.id] = {
        "prize": prize,
        "donor": donor,
        "end_time": end_time,
        "channel": interaction.channel.id,
        "entries": set(),
        "role": role,
        "message": message
    }
    await interaction.response.send_message(f"Giveaway started for **{prize}**!", ephemeral=True)

class JoinButtonView(discord.ui.View):
    def __init__(self, channel_id, prize, donor, role, end_time):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        self.prize = prize
        self.donor = donor
        self.role = role
        self.end_time = end_time

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        message_id = interaction.message.id
        giveaway_data = giveaways.get(message_id)

        if not giveaway_data:
            await interaction.response.send_message("This giveaway is no longer active.", ephemeral=True)
            return

        if giveaway_data["role"] and giveaway_data["role"] not in interaction.user.roles:
            await interaction.response.send_message("You don't have the required role to join this giveaway.", ephemeral=True)
            return

        if interaction.user.id in giveaway_data["entries"]:
            await interaction.response.send_message("You've already joined this giveaway!", ephemeral=True)
            return

        giveaway_data["entries"].add(interaction.user.id)
        await interaction.response.send_message("You've successfully entered the giveaway!", ephemeral=True)

async def check_giveaways():
    while True:
        now = datetime.now(UTC)
        to_remove = []

        for message_id, data in list(giveaways.items()):
            if now >= data["end_time"]:
                channel = bot.get_channel(data["channel"])
                if not channel:
                    continue
                try:
                    message = await channel.fetch_message(message_id)
                except:
                    continue

                entries = list(data["entries"])
                if entries:
                    winner_id = random.choice(entries)
                    winner = await bot.fetch_user(winner_id)
                    result = f"🎉 Congratulations {winner.mention}! You won **{data['prize']}**!"
                else:
                    result = "No one entered the giveaway."

                await channel.send(f"**Giveaway Ended!**\n{result}")
                await message.edit(view=None)
                to_remove.append(message_id)

        for message_id in to_remove:
            giveaways.pop(message_id, None)

        await asyncio.sleep(120)  # check every 2 minutes

@bot.event
async def on_message(message):
    await bot.process_commands(message)

# Start background giveaway checker
bot.loop.create_task(check_giveaways())

# Start keep_alive server
keep_alive()

# Run bot
bot.run(TOKEN)
