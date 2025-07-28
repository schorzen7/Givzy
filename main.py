import os
import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
from keep_alive import keep_alive
from datetime import datetime, timedelta

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
GUILD_ID = int(os.getenv("GUILD_ID"))  # Make sure this is set in your .env or Render variables

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = app_commands.CommandTree(bot)

giveaways = {}  # giveaway_id: {message, participants, end_time, ...}

@bot.event
async def on_ready():
    try:
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"Synced {len(synced)} commands to guild {GUILD_ID}.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    print(f"Logged in as {bot.user}.")

@tree.command(name="giveaway", description="Start a giveaway", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(
    prize="What is the prize?",
    duration="Duration in seconds",
    donor="Who is donating?",
    role="Optional role required to join"
)
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str, role: discord.Role = None):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    await interaction.response.defer()

    embed = discord.Embed(title="🎉 Giveaway 🎉", description=f"**Prize:** {prize}\n**Donor:** {donor}\nReact with the button to join!\n\n⏰ Time Remaining: `{duration}` seconds\n👥 Participants: 0", color=0x00ff00)
    embed.set_footer(text="Good luck!")
    view = GiveawayView(interaction.channel, duration, prize, donor, role, interaction.user)
    message = await interaction.followup.send(embed=embed, view=view)

    view.message = message
    view.embed = embed
    view.task.start()

class GiveawayView(discord.ui.View):
    def __init__(self, channel, duration, prize, donor, role_required, host):
        super().__init__(timeout=duration)
        self.channel = channel
        self.duration = duration
        self.prize = prize
        self.donor = donor
        self.role_required = role_required
        self.host = host
        self.participants = set()
        self.message = None
        self.embed = None
        self.end_time = datetime.utcnow() + timedelta(seconds=duration)
        self.task = tasks.loop(seconds=1)(self.update_countdown)

    async def update_countdown(self):
        if self.message:
            remaining = int((self.end_time - datetime.utcnow()).total_seconds())
            if remaining <= 0:
                self.task.cancel()
                await self.end_giveaway()
                return
            self.embed.description = f"**Prize:** {self.prize}\n**Donor:** {self.donor}\nReact with the button to join!\n\n⏰ Time Remaining: `{remaining}` seconds\n👥 Participants: {len(self.participants)}"
            await self.message.edit(embed=self.embed, view=self)

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.role_required and self.role_required not in interaction.user.roles:
            await interaction.response.send_message(f"You need the role {self.role_required.mention} to join.", ephemeral=True)
            return
        if interaction.user.id in self.participants:
            await interaction.response.send_message("You already joined!", ephemeral=True)
        else:
            self.participants.add(interaction.user.id)
            await interaction.response.send_message("You joined the giveaway!", ephemeral=True)

    async def end_giveaway(self):
        for child in self.children:
            child.disabled = True
        await self.message.edit(view=self)
        if not self.participants:
            await self.channel.send("❌ No one participated in the giveaway.")
        else:
            winner_id = list(self.participants)[0]
            winner = self.message.guild.get_member(winner_id)
            await self.channel.send(f"🎊 Congratulations {winner.mention}! You won the **{self.prize}**!")
            if LOG_CHANNEL_ID:
                log_channel = self.message.guild.get_channel(int(LOG_CHANNEL_ID))
                if log_channel:
                    await log_channel.send(f"{winner.mention} won the **{self.prize}** donated by {self.donor} in a giveaway hosted by {self.host.mention}.")

keep_alive()
bot.run(TOKEN)
