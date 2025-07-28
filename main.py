import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import asyncio
import random
import datetime
import pytz
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

active_giveaways = {}

@tree.command(name="giveaway", description="Start a giveaway!")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(
    duration="Duration in seconds",
    prize="The prize for the giveaway",
    donor="Who is donating the prize?",
    role="Optional role required to join"
)
async def giveaway(interaction: discord.Interaction, duration: int, prize: str, donor: str, role: discord.Role = None):
    embed = discord.Embed(title="🎉 Giveaway Started!", color=discord.Color.gold())
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Donor", value=donor, inline=False)
    embed.add_field(name="Ends In", value=f"{duration} seconds", inline=False)
    embed.set_footer(text=f"Hosted by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

    join_button = discord.ui.Button(label="Join Giveaway", style=discord.ButtonStyle.green, custom_id="join_giveaway")
    cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger, custom_id="cancel_giveaway")

    class GiveawayView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
            self.participants = set()

        @discord.ui.button(label="Join Giveaway", style=discord.ButtonStyle.green, custom_id="join_giveaway")
        async def join_callback(self, interaction_btn: discord.Interaction, button: discord.ui.Button):
            if role and role not in interaction_btn.user.roles:
                await interaction_btn.response.send_message("❌ You don't have the required role to join.", ephemeral=True)
                return
            if interaction_btn.user.id in self.participants:
                await interaction_btn.response.send_message("❗ You've already joined!", ephemeral=True)
            else:
                self.participants.add(interaction_btn.user.id)
                await interaction_btn.response.send_message("✅ You've joined the giveaway!", ephemeral=True)
                await msg.edit(embed=update_embed(embed, len(self.participants)))

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, custom_id="cancel_giveaway")
        async def cancel_callback(self, interaction_btn: discord.Interaction, button: discord.ui.Button):
            if interaction_btn.user != interaction.user:
                await interaction_btn.response.send_message("Only the host can cancel this giveaway.", ephemeral=True)
                return
            await interaction_btn.response.send_message("🛑 Giveaway canceled.")
            await msg.edit(content="~~Giveaway canceled~~", view=None, embed=None)
            self.stop()

    view = GiveawayView()
    msg = await interaction.response.send_message(embed=embed, view=view)
    response = await interaction.original_response()

    # Countdown task (edit every second)
    async def countdown_timer():
        nonlocal duration
        try:
            while duration > 0:
                await asyncio.sleep(1)
                duration -= 1
                embed.set_field_at(2, name="Ends In", value=f"{duration} seconds", inline=False)
                try:
                    await response.edit(embed=embed)
                except Exception:
                    break
        except Exception as e:
            print("Countdown Error:", e)

    bot.loop.create_task(countdown_timer())

    await asyncio.sleep(duration)

    if len(view.participants) == 0:
        await response.edit(content="No participants joined the giveaway.", embed=None, view=None)
        return

    winner_id = random.choice(list(view.participants))
    winner = await bot.fetch_user(winner_id)

    result_embed = discord.Embed(title="🎉 Giveaway Ended!", description=f"Winner: {winner.mention}", color=discord.Color.green())
    result_embed.add_field(name="Prize", value=prize)
    result_embed.set_footer(text=f"Hosted by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

    await response.edit(embed=result_embed, view=None)

@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"{bot.user} is ready.")

bot.run(TOKEN)
