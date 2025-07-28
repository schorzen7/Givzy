import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
import asyncio
import os
import json
from datetime import datetime, timedelta, timezone
from keep_alive import keep_alive
from dotenv import load_dotenv

load_dotenv()  # Load .env if present

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

giveaways_data = {}

class JoinButton(Button):
    def __init__(self, giveaway_id):
        super().__init__(label="🎉 Join", style=discord.ButtonStyle.green)
        self.giveaway_id = giveaway_id

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        if user_id in giveaways_data[self.giveaway_id]["participants"]:
            await interaction.response.send_message("You already joined this giveaway.", ephemeral=True)
        else:
            giveaways_data[self.giveaway_id]["participants"].append(user_id)
            await interaction.response.send_message("You have joined the giveaway!", ephemeral=True)

class GiveawayView(View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.add_item(JoinButton(giveaway_id))

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Sync failed: {e}")

@bot.tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    duration="Duration in seconds",
    prize="What is the prize?",
    donor="Who's giving the prize?"
)
async def giveaway(interaction: discord.Interaction, duration: int, prize: str, donor: str):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("You don’t have permission to start a giveaway.", ephemeral=True)
        return

    giveaway_id = str(interaction.id)
    giveaways_data[giveaway_id] = {
        "participants": [],
        "end_time": datetime.now(timezone.utc) + timedelta(seconds=duration),
        "prize": prize,
        "donor": donor
    }

    embed = discord.Embed(title="🎉 Giveaway Started!", color=0x00ff00)
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Donor", value=donor, inline=False)
    embed.add_field(name="Time Left", value=f"{duration} seconds", inline=False)
    embed.add_field(name="Participants", value="0", inline=False)
    embed.set_footer(text="Click the Join button below to enter!")

    view = GiveawayView(giveaway_id)
    
    try:
        message = await interaction.channel.send(embed=embed, view=view)
    except discord.Forbidden:
        await interaction.response.send_message("Bot is missing permission to send messages in this channel.", ephemeral=True)
        return

    await interaction.response.send_message("Giveaway started!", ephemeral=True)

    for remaining in range(duration, 0, -1):
        await asyncio.sleep(1)
        embed.set_field_at(2, name="Time Left", value=f"{remaining} seconds", inline=False)
        embed.set_field_at(3, name="Participants", value=str(len(giveaways_data[giveaway_id]["participants"])), inline=False)
        try:
            await message.edit(embed=embed, view=view)
        except discord.Forbidden:
            break

    participants = giveaways_data[giveaway_id]["participants"]
    if participants:
        winner_id = int(participants[0])  # for now, pick the first
        winner = interaction.guild.get_member(winner_id)
        await interaction.channel.send(f"🎉 Congratulations {winner.mention}, you won **{prize}**!")
    else:
        await interaction.channel.send("😢 No one joined the giveaway.")

    del giveaways_data[giveaway_id]

keep_alive()  # optional keep-alive server

# Make sure TOKEN is set as an environment variable
bot.run(os.getenv("TOKEN"))
