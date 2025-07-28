import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random
import os
from datetime import datetime, timedelta
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}

class JoinButton(discord.ui.View):
    def __init__(self, message_id):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.success, custom_id="join_button")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway_data = giveaways.get(self.message_id)
        if giveaway_data:
            if interaction.user.id in giveaway_data["participants"]:
                await interaction.response.send_message("You already joined the giveaway!", ephemeral=True)
            else:
                giveaway_data["participants"].append(interaction.user.id)
                await interaction.response.send_message("You've joined the giveaway!", ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger, custom_id="cancel_button")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway_data = giveaways.get(self.message_id)
        if giveaway_data and interaction.user.id in giveaway_data["participants"]:
            giveaway_data["participants"].remove(interaction.user.id)
            await interaction.response.send_message("You left the giveaway.", ephemeral=True)
        else:
            await interaction.response.send_message("You are not in the giveaway.", ephemeral=True)

    @discord.ui.button(label="🔁 Reroll", style=discord.ButtonStyle.secondary, custom_id="reroll_button")
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway_data = giveaways.get(self.message_id)
        if giveaway_data and interaction.user.guild_permissions.manage_messages:
            await end_giveaway(interaction.message, interaction.message.embeds[0], giveaway_data, reroll=True)
            await interaction.response.send_message("Rerolled the giveaway!", ephemeral=True)
        else:
            await interaction.response.send_message("You don't have permission to reroll.", ephemeral=True)

async def countdown(duration, message, embed, giveaway_data):
    end_time = datetime.utcnow() + timedelta(seconds=duration)

    while True:
        now = datetime.utcnow()
        remaining = end_time - now

        if remaining.total_seconds() <= 0:
            break

        hours, remainder = divmod(int(remaining.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        time_display = f"{hours:02}:{minutes:02}:{seconds:02}"

        embed.set_footer(text=f"Ends in: {time_display} • Participants: {len(giveaway_data['participants'])}")
        try:
            await message.edit(embed=embed)
        except discord.NotFound:
            print("❗ Giveaway message was deleted or not found. Countdown cancelled.")
            return
        except Exception as e:
            print(f"⚠️ Unexpected error during countdown: {e}")
            return

        await asyncio.sleep(1)

    await end_giveaway(message, embed, giveaway_data)

async def end_giveaway(message, embed, giveaway_data, reroll=False):
    participants = giveaway_data["participants"]
    if not participants:
        embed.color = discord.Color.red()
        embed.set_footer(text="Giveaway ended. No participants.")
        await message.edit(embed=embed, view=None)
        return

    winner_id = random.choice(participants)
    winner = message.guild.get_member(winner_id)

    embed.color = discord.Color.green()
    embed.set_footer(text="Giveaway ended!")
    embed.add_field(name="🎉 Winner", value=f"{winner.mention if winner else 'Unknown User'}", inline=False)
    await message.edit(embed=embed, view=None)

    try:
        await message.channel.send(f"🎉 Congratulations {winner.mention if winner else 'Unknown User'}! You won **{giveaway_data['prize']}**!")
    except Exception as e:
        print(f"Failed to announce winner: {e}")

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    prize="The giveaway prize",
    duration="Duration in seconds",
    donor="Who is giving this prize?"
)
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str):
    embed = discord.Embed(title="🎉 Giveaway", description=f"**Prize:** {prize}\n**Donor:** {donor}", color=discord.Color.purple())
    embed.set_footer(text="Starting...")
    view = JoinButton(message_id=None)

    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()

    view.message_id = message.id
    giveaways[message.id] = {
        "participants": [],
        "prize": prize
    }

    await countdown(duration, message, embed, giveaways[message.id])

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
