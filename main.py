import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import asyncio
import os
from typing import Optional
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}  # To store ongoing giveaways

class GiveawayView(discord.ui.View):
    def __init__(self, timeout, role, interaction):
        super().__init__(timeout=timeout)
        self.entries = set()
        self.role = role
        self.interaction = interaction

    @discord.ui.button(label="🎉 Join Giveaway", style=discord.ButtonStyle.green)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if self.role and self.role not in user.roles:
            await interaction.response.send_message(
                f"❌ You need the `{self.role.name}` role to join this giveaway.", ephemeral=True
            )
            return

        if user.id in self.entries:
            await interaction.response.send_message("⚠️ You have already joined this giveaway.", ephemeral=True)
        else:
            self.entries.add(user.id)
            await interaction.response.send_message("✅ You have successfully joined the giveaway!", ephemeral=True)

    @discord.ui.button(label="❌ Cancel Entry", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id in self.entries:
            self.entries.remove(user.id)
            await interaction.response.send_message("🚫 You have left the giveaway.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ You are not part of this giveaway.", ephemeral=True)

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    prize="What is the prize?",
    duration="How long should the giveaway last? (e.g., 10s, 5m, 1h)",
    name="Who donated this giveaway?",
    role="Optional role required to join"
)
async def giveaway(interaction: discord.Interaction, prize: str, duration: str, name: str, role: Optional[discord.Role] = None):
    await interaction.response.defer()  # ✅ Prevents timeout error

    # Parse duration
    unit = duration[-1]
    if unit not in ["s", "m", "h"]:
        await interaction.followup.send("❌ Invalid duration format. Use s, m, or h (e.g., 30s, 5m, 1h).")
        return

    try:
        time = int(duration[:-1])
        if unit == "m":
            time *= 60
        elif unit == "h":
            time *= 3600
    except ValueError:
        await interaction.followup.send("❌ Invalid duration number.")
        return

    view = GiveawayView(timeout=time, role=role, interaction=interaction)
    embed = discord.Embed(title="🎁 New Giveaway!", color=discord.Color.gold())
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Donated by", value=name, inline=True)
    embed.add_field(name="Duration", value=duration, inline=True)
    if role:
        embed.add_field(name="Required Role", value=role.mention, inline=False)
    embed.set_footer(text="Click the button below to join!")

    message = await interaction.followup.send(embed=embed, view=view)

    await asyncio.sleep(time)

    if not view.entries:
        await interaction.followup.send("😢 No one joined the giveaway.")
        return

    winner_id = random.choice(list(view.entries))
    winner = interaction.guild.get_member(winner_id)
    if winner:
        await interaction.followup.send(f"🎉 Congratulations {winner.mention}, you won **{prize}**!")
    else:
        await interaction.followup.send("⚠️ Winner could not be found.")

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user}")

# ✅ Start the web server to keep the bot alive
keep_alive()

# ✅ Start the bot
bot.run(os.getenv("TOKEN"))
