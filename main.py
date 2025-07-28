import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button
import asyncio
import datetime
import os
import random
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}  # giveaway_id: Giveaway instance

class Giveaway:
    def __init__(self, ctx, prize, duration, donor, role_requirement=None):
        self.ctx = ctx
        self.prize = prize
        self.duration = duration
        self.donor = donor
        self.role_requirement = role_requirement
        self.end_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=duration)
        self.participants = set()
        self.message = None
        self.task = None
        self.view = None
        self.cancelled = False
        self.channel = ctx.channel
        self.winners = []

    async def start(self):
        embed = discord.Embed(title="🎉 Giveaway Started!", color=discord.Color.gold())
        embed.add_field(name="Prize", value=self.prize, inline=False)
        embed.add_field(name="Donor", value=self.donor.mention, inline=False)
        embed.add_field(name="Duration", value=f"<t:{int(self.end_time.timestamp())}:R>", inline=False)
        if self.role_requirement:
            embed.add_field(name="Role Requirement", value=self.role_requirement.mention, inline=False)
        embed.add_field(name="Participants", value="0", inline=False)

        self.view = View(timeout=None)
        self.view.add_item(Button(label="Join", style=discord.ButtonStyle.green, custom_id="join_giveaway"))
        self.view.add_item(Button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel_giveaway"))
        self.view.add_item(Button(label="Reroll", style=discord.ButtonStyle.blurple, custom_id="reroll_giveaway"))

        self.message = await self.ctx.channel.send(embed=embed, view=self.view)
        giveaways[self.message.id] = self

        self.task = asyncio.create_task(self.update_countdown(self.end_time))

    async def update_countdown(self, end_time):
        while datetime.datetime.utcnow() < end_time and not self.cancelled:
            remaining = int((end_time - datetime.datetime.utcnow()).total_seconds())
            embed = self.message.embeds[0]
            embed.set_field_at(2, name="Duration", value=f"<t:{int(end_time.timestamp())}:R>", inline=False)
            embed.set_field_at(-1, name="Participants", value=str(len(self.participants)), inline=False)
            await self.message.edit(embed=embed, view=self.view)
            await asyncio.sleep(5)  # ✅ 5 seconds interval

        if not self.cancelled:
            await self.end()

    async def join(self, user):
        if self.role_requirement and self.role_requirement not in user.roles:
            return await user.send("You do not have the required role to join this giveaway.")
        if user.id in self.participants:
            return await user.send("You are already entered in this giveaway.")
        self.participants.add(user.id)
        await user.send(f"You have successfully joined the giveaway for **{self.prize}**!")

    async def reroll(self, interaction):
        if not self.participants:
            await interaction.response.send_message("No participants to choose from!", ephemeral=True)
            return
        new_winner_id = random.choice(list(self.participants))
        new_winner = interaction.guild.get_member(new_winner_id)
        self.winners = [new_winner]
        await self.ctx.send(f"🎉 New winner: {new_winner.mention} for **{self.prize}**!")
        await interaction.response.send_message("Rerolled the giveaway!", ephemeral=True)

    async def cancel(self):
        self.cancelled = True
        embed = self.message.embeds[0]
        embed.title = "❌ Giveaway Cancelled"
        await self.message.edit(embed=embed, view=None)

    async def end(self):
        if self.cancelled:
            return
        if not self.participants:
            embed = self.message.embeds[0]
            embed.title = "😢 Giveaway Ended - No Participants"
            await self.message.edit(embed=embed, view=None)
            return
        winner_id = random.choice(list(self.participants))
        winner = self.ctx.guild.get_member(winner_id)
        self.winners = [winner]
        embed = self.message.embeds[0]
        embed.title = "🎉 Giveaway Ended!"
        embed.add_field(name="Winner", value=winner.mention, inline=False)
        await self.message.edit(embed=embed, view=None)
        await self.ctx.send(f"🎉 Congratulations {winner.mention}! You won **{self.prize}**!")

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    prize="Prize for the giveaway",
    duration="Duration in seconds",
    role="Optional role requirement"
)
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, role: discord.Role = None):
    await interaction.response.send_message("🎉 Giveaway is starting...", ephemeral=True)
    ctx = await bot.get_context(interaction)
    g = Giveaway(ctx, prize, duration, interaction.user, role)
    await g.start()

@bot.event
async def on_ready():
    print(f"{bot.user} is ready.")
    await tree.sync()

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data["custom_id"]
        giveaway = giveaways.get(interaction.message.id)
        if not giveaway:
            return
        if custom_id == "join_giveaway":
            await giveaway.join(interaction.user)
            await interaction.response.defer()
        elif custom_id == "cancel_giveaway" and interaction.user.guild_permissions.manage_guild:
            await giveaway.cancel()
            await interaction.response.send_message("Giveaway cancelled.", ephemeral=True)
        elif custom_id == "reroll_giveaway" and interaction.user.guild_permissions.manage_guild:
            await giveaway.reroll(interaction)

keep_alive()

TOKEN = os.environ.get("DISCORD_TOKEN")
bot.run(TOKEN)
