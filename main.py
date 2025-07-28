import os
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
from dotenv import load_dotenv
import asyncio
import datetime

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
giveaways = {}

class GiveawayButton(ui.View):
    def __init__(self, message_id):
        super().__init__(timeout=None)
        self.message_id = message_id

    @ui.button(label="🎉 Join Giveaway", style=discord.ButtonStyle.green, custom_id="join_button")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = giveaways.get(self.message_id)
        if not giveaway:
            await interaction.response.send_message("This giveaway is no longer active.", ephemeral=True)
            return

        required_role = giveaway.get("required_role")
        if required_role and required_role not in [role.id for role in interaction.user.roles]:
            await interaction.response.send_message(f"You must have the required role to join this giveaway.", ephemeral=True)
            return

        if interaction.user.id in giveaway["participants"]:
            await interaction.response.send_message("You have already joined this giveaway.", ephemeral=True)
            return

        giveaway["participants"].append(interaction.user.id)
        await interaction.response.send_message("You have successfully joined the giveaway!", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    prize="The prize of the giveaway",
    duration="Duration in seconds",
    donor="The name of the person donating the prize",
    role="Optional role required to join the giveaway"
)
@app_commands.checks.has_permissions(manage_messages=True)
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str, role: discord.Role = None):
    embed = discord.Embed(
        title="🎁 Giveaway!",
        description=f"**Prize:** {prize}\n**Donor:** {donor}\n**Ends in:** {duration} seconds\n",
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Join now by clicking the button below!")

    view = GiveawayButton(message_id=None)
    message = await interaction.channel.send(embed=embed, view=view)

    giveaways[message.id] = {
        "prize": prize,
        "donor": donor,
        "participants": [],
        "end_time": datetime.datetime.utcnow() + datetime.timedelta(seconds=duration),
        "required_role": role.id if role else None,
        "message": message
    }

    view.message_id = message.id  # Set message ID after sending
    await interaction.response.send_message(f"Giveaway started for **{prize}**!", ephemeral=True)

    await asyncio.sleep(duration)

    giveaway = giveaways.pop(message.id, None)
    if not giveaway:
        return

    participants = giveaway["participants"]
    if not participants:
        await message.reply("No one participated in the giveaway.")
        return

    winner_id = random.choice(participants)
    winner = interaction.guild.get_member(winner_id)
    await message.reply(f"🎉 Congratulations {winner.mention}! You won **{prize}**!")

@giveaway.error
async def giveaway_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("You need the **Manage Messages** permission to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message("An error occurred while running the command.", ephemeral=True)
        print(f"Error in /giveaway: {error}")

bot.run(TOKEN)
