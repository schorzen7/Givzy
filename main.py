import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
import random
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()

TOKEN = os.getenv("TOKEN")
GUILD_ID = discord.Object(id=int(os.getenv("GUILD_ID")))
OWNER_ID = int(os.getenv("OWNER_ID"))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}

class GiveawayView(discord.ui.View):
    def __init__(self, interaction, message, duration, prize, donor, required_role=None):
        super().__init__(timeout=None)
        self.interaction = interaction
        self.message = message
        self.duration = duration
        self.prize = prize
        self.donor = donor
        self.required_role = required_role
        self.participants = set()
        self.running = True
        self.message_id = message.id
        giveaways[self.message_id] = self

        self.update_task = bot.loop.create_task(self.live_countdown())

    async def live_countdown(self):
        remaining = self.duration
        while remaining > 0 and self.running:
            embed = self.create_embed(remaining)
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.NotFound:
                break
            await asyncio.sleep(1)
            remaining -= 1
        if self.running:
            await self.end_giveaway()

    def create_embed(self, remaining):
        embed = discord.Embed(
            title="🎉 Giveaway!",
            description=f"**Prize:** {self.prize}\n**Donor:** {self.donor.mention}\n\n"
                        f"Ends in: <t:{int(discord.utils.utcnow().timestamp()) + remaining}:R>\n"
                        f"Participants: **{len(self.participants)}**",
            color=discord.Color.green()
        )
        if self.required_role:
            embed.set_footer(text=f"Requires role: {self.required_role.name}")
        return embed

    async def end_giveaway(self):
        self.running = False
        if not self.participants:
            await self.message.channel.send("❌ Giveaway ended with no participants.")
        else:
            winner = random.choice(list(self.participants))
            await self.message.channel.send(f"🎉 Congratulations {winner.mention}, you won **{self.prize}**!")
        del giveaways[self.message_id]

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green, custom_id="join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.running:
            await interaction.response.send_message("❌ This giveaway has already ended.", ephemeral=True)
            return
        if self.required_role and self.required_role not in interaction.user.roles:
            await interaction.response.send_message(f"❌ You need the `{self.required_role.name}` role to join.", ephemeral=True)
            return
        if interaction.user in self.participants:
            await interaction.response.send_message("⚠️ You have already joined.", ephemeral=True)
        else:
            self.participants.add(interaction.user)
            await interaction.response.send_message("✅ You joined the giveaway!", ephemeral=True)

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(prize="Prize of the giveaway", duration="Duration in seconds", role="Role required to enter (optional)")
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, role: discord.Role = None):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    embed = discord.Embed(title="🎉 Giveaway Starting...", color=discord.Color.green())
    embed.description = f"**Prize:** {prize}\n**Donor:** {interaction.user.mention}\nEnds in: <t:{int(discord.utils.utcnow().timestamp()) + duration}:R>\nParticipants: **0**"
    if role:
        embed.set_footer(text=f"Requires role: {role.name}")

    view = GiveawayView(interaction, None, duration, prize, interaction.user, role)
    message = await interaction.channel.send(embed=embed, view=view)
    view.message = message
    await interaction.response.send_message("✅ Giveaway started!", ephemeral=True)

@tree.command(name="reroll", description="Reroll a giveaway")
@app_commands.describe(message_id="The message ID of the giveaway")
async def reroll(interaction: discord.Interaction, message_id: str):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    message_id = int(message_id)
    giveaway = giveaways.get(message_id)
    if not giveaway or not giveaway.participants:
        await interaction.response.send_message("❌ Giveaway not found or no participants.", ephemeral=True)
        return

    winner = random.choice(list(giveaway.participants))
    await interaction.channel.send(f"🔁 New winner: {winner.mention} for **{giveaway.prize}**!")
    await interaction.response.send_message("✅ Rerolled!", ephemeral=True)

@tree.command(name="cancel", description="Cancel a running giveaway")
@app_commands.describe(message_id="The message ID of the giveaway")
async def cancel(interaction: discord.Interaction, message_id: str):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    message_id = int(message_id)
    giveaway = giveaways.get(message_id)
    if not giveaway:
        await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
        return

    giveaway.running = False
    giveaways.pop(message_id, None)
    await interaction.channel.send("🚫 Giveaway has been cancelled.")
    await interaction.response.send_message("✅ Giveaway cancelled.", ephemeral=True)

@bot.event
async def on_ready():
    await tree.sync(guild=GUILD_ID)
    print(f"Bot is ready. Logged in as {bot.user}.")

keep_alive()
bot.run(TOKEN)
