import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import random
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = discord.Object(id=int(os.getenv("GUILD_ID")))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}

@bot.event
async def on_ready():
    await tree.sync(guild=GUILD_ID)
    print(f"Logged in as {bot.user}")

class GiveawayView(discord.ui.View):
    def __init__(self, message, author, duration, prize, required_role=None):
        super().__init__(timeout=None)
        self.message = message
        self.author = author
        self.duration = duration
        self.prize = prize
        self.required_role = required_role
        self.participants = []

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.participants:
            await interaction.response.send_message("You already joined!", ephemeral=True)
            return

        if self.required_role and self.required_role not in interaction.user.roles:
            await interaction.response.send_message("You don't have the required role to join this giveaway!", ephemeral=True)
            return

        self.participants.append(interaction.user)
        await interaction.response.send_message("You've successfully joined the giveaway!", ephemeral=True)
        await self.update_message()

    async def update_message(self):
        embed = discord.Embed(
            title="🎉 Giveaway",
            description=f"**Prize:** {self.prize}\n"
                        f"**Donor:** {self.author.mention}\n"
                        f"**Time Left:** {self.duration} seconds\n"
                        f"**Participants:** {len(self.participants)}",
            color=discord.Color.blurple()
        )
        await self.message.edit(embed=embed, view=self)

    async def start_countdown(self):
        while self.duration > 0:
            await self.update_message()
            await asyncio.sleep(1)
            self.duration -= 1

        await self.update_message()

        if not self.participants:
            await self.message.channel.send("❌ Giveaway ended. No one participated.")
        else:
            winner = random.choice(self.participants)
            await self.message.channel.send(f"🎉 Congratulations {winner.mention}, you won **{self.prize}**!")

@tree.command(name="giveaway", description="Start a giveaway", guild=GUILD_ID)
@app_commands.describe(duration="How long in seconds", prize="What is the prize", donor="Who donated the prize", required_role="Optional role required to join")
async def giveaway(interaction: discord.Interaction, duration: int, prize: str, donor: str, required_role: discord.Role = None):
    await interaction.response.defer()
    embed = discord.Embed(
        title="🎉 Giveaway",
        description=f"**Prize:** {prize}\n"
                    f"**Donor:** {donor}\n"
                    f"**Time Left:** {duration} seconds\n"
                    f"**Participants:** 0",
        color=discord.Color.blurple()
    )
    message = await interaction.followup.send(embed=embed, wait=True)

    view = GiveawayView(message, interaction.user, duration, prize, required_role)
    giveaways[message.id] = view
    await message.edit(view=view)
    await view.start_countdown()

@tree.command(name="cancel", description="Cancel a giveaway by message ID", guild=GUILD_ID)
@app_commands.describe(message_id="The message ID of the giveaway")
async def cancel(interaction: discord.Interaction, message_id: str):
    try:
        message_id = int(message_id)
        view = giveaways.get(message_id)
        if view:
            del giveaways[message_id]
            await view.message.edit(content="🚫 Giveaway cancelled.", embed=None, view=None)
            await interaction.response.send_message("✅ Giveaway has been cancelled.")
        else:
            await interaction.response.send_message("⚠️ No active giveaway with that message ID.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)

@tree.command(name="reroll", description="Reroll a giveaway by message ID", guild=GUILD_ID)
@app_commands.describe(message_id="The message ID of the giveaway")
async def reroll(interaction: discord.Interaction, message_id: str):
    try:
        message_id = int(message_id)
        view = giveaways.get(message_id)
        if view and view.participants:
            winner = random.choice(view.participants)
            await interaction.response.send_message(f"🔁 New winner: {winner.mention} 🎉")
        else:
            await interaction.response.send_message("⚠️ No participants or invalid giveaway.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)

keep_alive()
bot.run(TOKEN)
