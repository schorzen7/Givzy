import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
import random
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaway_data = {}

class JoinButton(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

    @discord.ui.button(label="🎉 Join Giveaway", style=discord.ButtonStyle.green, custom_id="join_giveaway")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        data = giveaway_data.get(self.giveaway_id)
        if not data:
            await interaction.response.send_message("Giveaway not found or already ended.", ephemeral=True)
            return
        if user.id in data["participants"]:
            await interaction.response.send_message("You already joined this giveaway!", ephemeral=True)
            return
        if data["required_role"] and data["required_role"] not in getattr(user, "roles", []):
            await interaction.response.send_message("You do not have the required role to join this giveaway.", ephemeral=True)
            return
        data["participants"].append(user.id)
        await interaction.response.send_message("You have successfully joined the giveaway!", ephemeral=True)

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    prize="Prize to give away",
    duration="Duration in seconds",
    name="Name of the person who donated the giveaway",
    role="Role required to join (optional)"
)
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, name: str, role: discord.Role = None):
    end_time = duration
    participants = []

    embed = discord.Embed(title="🎉 New Giveaway!", color=discord.Color.gold())
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Donated by", value=name, inline=True)
    embed.add_field(name="Time Left", value=f"{end_time} seconds", inline=True)
    if role:
        embed.add_field(name="Requirement", value=f"Must have role: {role.mention}", inline=False)
    embed.add_field(name="Participants", value="0", inline=True)

    giveaway_id = f"{interaction.channel_id}-{interaction.id}"
    view = JoinButton(giveaway_id)

    message = await interaction.response.send_message(embed=embed, view=view)
    followup = await interaction.followup.fetch_message((await interaction.original_response()).id)

    giveaway_data[giveaway_id] = {
        "message": followup,
        "embed": embed,
        "participants": participants,
        "required_role": role,
        "channel": interaction.channel,
        "prize": prize
    }

    for i in range(end_time, 0, -1):
        await asyncio.sleep(1)
        embed.set_field_at(2, name="Time Left", value=f"{i-1} seconds", inline=True)
        embed.set_field_at(3 if role else 2, name="Participants", value=str(len(participants)), inline=True)
        await followup.edit(embed=embed, view=view)

    await asyncio.sleep(1)

    if participants:
        winner_id = random.choice(participants)
        winner = interaction.guild.get_member(winner_id)
        await interaction.followup.send(f"🎉 Congratulations {winner.mention}! You won **{prize}**!")
    else:
        await interaction.followup.send("😢 No one joined the giveaway.")

@bot.event
async def on_ready():
    print(f"Bot is ready. Logged in as {bot.user}.")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

# ✅ Start the web server to keep the bot alive
keep_alive()

bot.run(TOKEN)
