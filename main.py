import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
import random
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
token = os.getenv("TOKEN")
guild_id = int(os.getenv("GUILD_ID"))

bot = commands.Bot(command_prefix="!", intents=intents)
giveaways = {}  # giveaway_id: {"end_time": datetime, "participants": [], "prize": str, "donor": str, ...}

@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=guild_id))
    print(f"Logged in as {bot.user}")
    check_giveaway_end.start()

@bot.tree.command(name="giveaway", description="Start a giveaway", guild=discord.Object(id=guild_id))
@app_commands.describe(
    prize="What is the prize?",
    duration="Duration (e.g. 10s, 5m, 2h)",
    donor="Who is donating the prize?"
)
async def giveaway(interaction: discord.Interaction, prize: str, duration: str, donor: str):
    await interaction.response.defer()

    if not interaction.user.guild_permissions.manage_guild:
        await interaction.followup.send("❌ You don't have permission to start a giveaway.", ephemeral=True)
        return

    multiplier = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    unit = duration[-1]
    if unit not in multiplier:
        await interaction.followup.send("❌ Invalid duration format. Use s, m, h, or d (e.g. 10s, 2h)", ephemeral=True)
        return

    try:
        amount = int(duration[:-1])
    except ValueError:
        await interaction.followup.send("❌ Duration must start with a number.", ephemeral=True)
        return

    seconds = amount * multiplier[unit]
    end_time = datetime.now(timezone.utc) + timedelta(seconds=seconds)

    embed = discord.Embed(
        title="🎉 Giveaway! 🎉",
        description=(
            f"**Prize:** {prize}\n"
            f"**Donor:** {donor}\n"
            f"**Ends:** <t:{int(end_time.timestamp())}:F>"
        ),
        color=0x00ff00
    )
    embed.set_footer(text="Click the button below to enter!")

    join_button = discord.ui.Button(label="🎉 Join", style=discord.ButtonStyle.green, custom_id="join_giveaway")
    view = discord.ui.View()
    view.add_item(join_button)

    message = await interaction.followup.send(embed=embed, view=view)
    giveaways[message.id] = {
        "end_time": end_time,
        "participants": [],
        "prize": prize,
        "donor": donor,
        "channel_id": interaction.channel_id,
        "message_id": message.id
    }

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component and interaction.data['custom_id'] == 'join_giveaway':
        message_id = interaction.message.id
        user_id = interaction.user.id

        if message_id in giveaways:
            if user_id in giveaways[message_id]['participants']:
                await interaction.response.send_message("❌ You have already joined this giveaway!", ephemeral=True)
            else:
                giveaways[message_id]['participants'].append(user_id)
                await interaction.response.send_message("✅ You have joined the giveaway!", ephemeral=True)

@tasks.loop(seconds=120)
async def check_giveaway_end():
    now = datetime.now(timezone.utc)
    ended = []

    for message_id, data in list(giveaways.items()):
        if now >= data['end_time']:
            channel = bot.get_channel(data['channel_id'])
            if not channel:
                continue
            try:
                message = await channel.fetch_message(message_id)
            except:
                continue

            if data['participants']:
                winner_id = random.choice(data['participants'])
                winner = await bot.fetch_user(winner_id)
                await channel.send(f"🎉 Congratulations {winner.mention}! You won **{data['prize']}** (Donated by {data['donor']})!")
            else:
                await channel.send("😢 No one joined the giveaway.")

            try:
                await message.edit(view=None)
            except:
                pass

            ended.append(message_id)

    for message_id in ended:
        del giveaways[message_id]

bot.run(token)
