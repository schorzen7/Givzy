import os
import discord
import asyncio
import datetime
from discord.ext import commands, tasks
from discord import app_commands, Intents
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))

intents = Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}

@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

@tree.command(name="giveaway", description="Start a giveaway", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(prize="What is the prize?", duration="Duration in seconds", donor="Name of the donor", role="Role required to enter (optional)")
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str, role: discord.Role = None):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("You don't have permission to start a giveaway.", ephemeral=True)
        return

    embed = discord.Embed(title="🎉 Giveaway Started!", color=discord.Color.green())
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Donor", value=donor, inline=False)
    embed.add_field(name="Hosted by", value=interaction.user.mention, inline=False)
    embed.add_field(name="Ends In", value=f"<t:{int(datetime.datetime.utcnow().timestamp()) + duration}:R>", inline=False)
    if role:
        embed.add_field(name="Role Required", value=role.mention, inline=False)
    embed.set_footer(text="Click the button below to join!")

    view = JoinView(prize, duration, interaction.user, role)
    await interaction.response.send_message(embed=embed, view=view)
    msg = await interaction.original_response()
    view.message = msg
    await view.start_countdown()

class JoinView(discord.ui.View):
    def __init__(self, prize, duration, host, required_role=None):
        super().__init__(timeout=None)
        self.prize = prize
        self.duration = duration
        self.host = host
        self.required_role = required_role
        self.participants = set()
        self.message = None
        self.countdown_task = None

    async def start_countdown(self):
        end_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=self.duration)
        self.countdown_task = asyncio.create_task(self.update_countdown(end_time))

    async def update_countdown(self, end_time):
        while datetime.datetime.utcnow() < end_time:
            remaining = int((end_time - datetime.datetime.utcnow()).total_seconds())
            embed = self.message.embeds[0]
            embed.set_field_at(3, name="Ends In", value=f"<t:{int(end_time.timestamp())}:R>", inline=False)
            await self.message.edit(embed=embed, view=self)
            await asyncio.sleep(1)
        await self.end_giveaway()

    async def end_giveaway(self):
        if self.participants:
            winner = random.choice(list(self.participants))
            await self.message.channel.send(f"🎉 Congratulations {winner.mention}! You won **{self.prize}**!")
        else:
            await self.message.channel.send("😢 No one joined the giveaway.")

        for child in self.children:
            child.disabled = True
        await self.message.edit(view=self)

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.required_role and self.required_role not in interaction.user.roles:
            await interaction.response.send_message("You don't have the required role to enter this giveaway.", ephemeral=True)
            return

        if interaction.user in self.participants:
            await interaction.response.send_message("You've already joined this giveaway!", ephemeral=True)
        else:
            self.participants.add(interaction.user)
            await interaction.response.send_message("You've successfully joined the giveaway!", ephemeral=True)

keep_alive()
bot.run(TOKEN)
