import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
import random
import time
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()
TOKEN = os.getenv("TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}

class GiveawayView(discord.ui.View):
    def __init__(self, ctx, message_id, required_role=None):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.message_id = message_id
        self.required_role = required_role
        self.entries = set()

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green, custom_id="join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.required_role and self.required_role not in [role.id for role in interaction.user.roles]:
            await interaction.response.send_message("You don't have the required role to join this giveaway.", ephemeral=True)
            return

        if interaction.user.id in self.entries:
            await interaction.response.send_message("You already joined this giveaway!", ephemeral=True)
            return

        self.entries.add(interaction.user.id)
        await interaction.response.send_message("You joined the giveaway!", ephemeral=True)

        channel = bot.get_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(f"{interaction.user.mention} joined the giveaway in {interaction.channel.mention}.")

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger, custom_id="cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only admins can cancel the giveaway.", ephemeral=True)
            return

        giveaways.pop(self.message_id, None)
        await interaction.message.edit(content="❌ This giveaway has been cancelled.", embed=None, view=None)
        await interaction.response.send_message("Giveaway cancelled.", ephemeral=True)

    @discord.ui.button(label="🔄 Reroll", style=discord.ButtonStyle.blurple, custom_id="reroll")
    async def reroll_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only admins can reroll the giveaway.", ephemeral=True)
            return

        if not self.entries:
            await interaction.response.send_message("No one joined the giveaway!", ephemeral=True)
            return

        winner_id = random.choice(list(self.entries))
        winner = await interaction.guild.fetch_member(winner_id)
        await interaction.channel.send(f"🔄 New winner: {winner.mention}!")

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guilds(discord.Object(id=int(GUILD_ID)))
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str, required_role: discord.Role = None):
    await interaction.response.defer(thinking=True)  # Prevent 404 interaction error

    embed = discord.Embed(title="🎉 Giveaway Started!", color=discord.Color.gold())
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Duration", value=f"{duration} seconds", inline=False)
    embed.add_field(name="Donor", value=donor, inline=False)
    if required_role:
        embed.add_field(name="Required Role", value=required_role.mention, inline=False)
    embed.set_footer(text="Click the button below to join!")

    view = GiveawayView(interaction, message_id=None, required_role=required_role.id if required_role else None)
    msg = await interaction.followup.send(embed=embed, view=view)  # Use followup after defer
    view.message_id = msg.id
    giveaways[msg.id] = view

    await asyncio.sleep(duration)

    if view.entries:
        winner_id = random.choice(list(view.entries))
        winner = await interaction.guild.fetch_member(winner_id)
        await interaction.channel.send(f"🎉 Congratulations {winner.mention}, you won the giveaway for **{prize}**!")
    else:
        await interaction.channel.send("No one joined the giveaway.")

    await msg.edit(view=None)

@giveaway.error
async def giveaway_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("You don’t have permission to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message("An error occurred while processing the command.", ephemeral=True)

@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=int(GUILD_ID)))
    print(f"Bot is ready as {bot.user}")

keep_alive()
bot.run(TOKEN)
