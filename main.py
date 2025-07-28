import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button
import asyncio
import os
import datetime
import pytz
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}

class GiveawayView(View):
    def __init__(self, message_id):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green, custom_id="join_button")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = giveaways.get(self.message_id)
        if giveaway is None:
            await interaction.response.send_message("This giveaway is no longer active.", ephemeral=True)
            return

        if interaction.user.id in giveaway["participants"]:
            await interaction.response.send_message("You've already joined this giveaway.", ephemeral=True)
            return

        giveaway["participants"].append(interaction.user.id)
        await interaction.response.send_message("You've successfully joined the giveaway!", ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red, custom_id="cancel_button")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != giveaways.get(self.message_id, {}).get("host_id"):
            await interaction.response.send_message("Only the host can cancel this giveaway.", ephemeral=True)
            return

        giveaways.pop(self.message_id, None)
        await interaction.message.edit(content="❌ This giveaway has been canceled.", embed=None, view=None)
        await interaction.response.send_message("Giveaway canceled.", ephemeral=True)

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    prize="Prize of the giveaway",
    duration="Duration in minutes",
    donor="Donor of the prize",
    required_role="Role required to join (optional)"
)
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str, required_role: discord.Role = None):
    await interaction.response.defer()  # Fix: acknowledge interaction immediately

    end_time = datetime.datetime.now(pytz.utc) + datetime.timedelta(minutes=duration)
    embed = discord.Embed(title="🎉 New Giveaway!", color=discord.Color.green())
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Donor", value=donor, inline=False)
    embed.add_field(name="Ends At", value=f"<t:{int(end_time.timestamp())}:R>", inline=False)
    if required_role:
        embed.add_field(name="Requirement", value=required_role.mention, inline=False)
    embed.set_footer(text=f"Hosted by {interaction.user}")

    message = await interaction.followup.send(embed=embed, view=GiveawayView(None), wait=True)

    giveaways[message.id] = {
        "prize": prize,
        "end_time": end_time,
        "host_id": interaction.user.id,
        "participants": [],
        "required_role": required_role.id if required_role else None,
        "message": message,
    }

    view = GiveawayView(message.id)
    await message.edit(view=view)

    async def end_giveaway():
        await asyncio.sleep(duration * 60)
        giveaway = giveaways.pop(message.id, None)
        if giveaway:
            participants = giveaway["participants"]
            if not participants:
                await message.edit(content="😢 No one joined the giveaway.", embed=None, view=None)
                return
            winner_id = random.choice(participants)
            winner = await bot.fetch_user(winner_id)
            await message.edit(content=f"🎉 Congratulations {winner.mention}, you won **{prize}**!", embed=None, view=None)

    bot.loop.create_task(end_giveaway())

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

keep_alive()
bot.run(os.getenv("TOKEN"))
