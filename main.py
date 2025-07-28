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
GUILD_ID = discord.Object(id=int(os.getenv("GUILD_ID")))

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

giveaway_data = {}

@bot.event
async def on_ready():
    await bot.tree.sync(guild=GUILD_ID)
    print(f'Logged in as {bot.user.name}')

class GiveawayView(discord.ui.View):
    def __init__(self, ctx, duration, prize, donor, required_role=None):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.duration = duration
        self.prize = prize
        self.donor = donor
        self.required_role = required_role
        self.entries = set()
        self.message = None
        self.end_time = time.time() + duration

        self.update_task = bot.loop.create_task(self.update_countdown())

    async def update_countdown(self):
        while time.time() < self.end_time:
            if self.message:
                remaining = int(self.end_time - time.time())
                embed = self.create_embed(remaining)
                try:
                    await self.message.edit(embed=embed, view=self)
                except discord.NotFound:
                    break
            await asyncio.sleep(1)
        await self.end_giveaway()

    def create_embed(self, remaining):
        embed = discord.Embed(
            title="🎉 Giveaway Time!",
            description=f"**Prize:** {self.prize}\n**Donor:** {self.donor}\n\n"
                        f"⏰ **Time Left:** {remaining} seconds\n"
                        f"👥 **Participants:** {len(self.entries)}",
            color=discord.Color.gold()
        )
        if self.required_role:
            embed.add_field(name="🔒 Role Required", value=self.required_role.mention)
        return embed

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.required_role and self.required_role not in interaction.user.roles:
            await interaction.response.send_message("You don't have the required role to join this giveaway.", ephemeral=True)
            return
        if interaction.user.id in self.entries:
            await interaction.response.send_message("You're already entered in the giveaway.", ephemeral=True)
        else:
            self.entries.add(interaction.user.id)
            await interaction.response.send_message("You have entered the giveaway!", ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.user:
            await interaction.response.send_message("Only the giveaway creator can cancel it.", ephemeral=True)
            return
        self.update_task.cancel()
        await self.message.edit(content="🚫 Giveaway cancelled.", embed=None, view=None)
        self.stop()

    @discord.ui.button(label="🔄 Reroll", style=discord.ButtonStyle.blurple)
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.user:
            await interaction.response.send_message("Only the giveaway creator can reroll.", ephemeral=True)
            return
        if not self.entries:
            await interaction.response.send_message("No entries to reroll.", ephemeral=True)
            return
        winner_id = random.choice(list(self.entries))
        winner = await interaction.client.fetch_user(winner_id)
        await interaction.response.send_message(f"🎉 New winner: {winner.mention}!", ephemeral=False)

    async def end_giveaway(self):
        if not self.entries:
            await self.message.edit(content="😢 No one entered the giveaway.", embed=None, view=None)
        else:
            winner_id = random.choice(list(self.entries))
            winner = await bot.fetch_user(winner_id)
            await self.message.channel.send(f"🎉 Congratulations {winner.mention}! You won **{self.prize}** donated by {self.donor}!")
        await self.message.edit(view=None)
        self.stop()

@bot.tree.command(name="giveaway", description="Start a giveaway", guild=GUILD_ID)
@app_commands.describe(prize="What is the prize?",
                       duration="Duration in seconds",
                       donor="Who donated the prize?",
                       required_role="Role required to join (optional)")
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str, required_role: discord.Role = None):
    view = GiveawayView(interaction, duration, prize, donor, required_role)
    embed = view.create_embed(duration)
    await interaction.response.send_message(embed=embed, view=view)
    view.message = await interaction.original_response()

keep_alive()
bot.run(TOKEN)
