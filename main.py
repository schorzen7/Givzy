import os
import discord
from discord.ext import commands, tasks
from discord import app_commands, ButtonStyle, Interaction
from discord.ui import Button, View
import asyncio
from datetime import datetime, timedelta
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = app_commands.CommandTree(bot)

giveaways = {}

@bot.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {bot.user}")
    giveaway_check.start()

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(
    duration="Duration (e.g. 30s, 10m, 2h, 1d)",
    prize="Prize of the giveaway",
    donor="Donor name",
    role="Optional role required to join"
)
async def giveaway_command(
    interaction: Interaction,
    duration: str,
    prize: str,
    donor: str,
    role: discord.Role = None
):
    await interaction.response.defer(ephemeral=True)

    unit = duration[-1]
    try:
        time = int(duration[:-1])
    except ValueError:
        await interaction.followup.send("Invalid duration format. Use s, m, h, or d.")
        return

    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if unit not in multiplier:
        await interaction.followup.send("Invalid time unit. Use s, m, h, or d.")
        return

    seconds = time * multiplier[unit]
    end_time = datetime.utcnow() + timedelta(seconds=seconds)

    join_button = Button(label="Join", style=ButtonStyle.green, custom_id="join_button")
    view = View(timeout=None)
    view.add_item(join_button)

    embed = discord.Embed(title="🎉 Giveaway", color=discord.Color.green())
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Donor", value=donor, inline=False)
    if role:
        embed.add_field(name="Required Role", value=role.mention, inline=False)
    embed.set_footer(text=f"Ends at")
    embed.timestamp = end_time

    message = await interaction.channel.send(embed=embed, view=view)
    giveaways[message.id] = {
        "channel_id": message.channel.id,
        "message_id": message.id,
        "end_time": end_time,
        "participants": [],
        "prize": prize,
        "donor": donor,
        "role_id": role.id if role else None
    }

    await interaction.followup.send(f"Giveaway started for **{prize}**!", ephemeral=True)

@bot.event
async def on_interaction(interaction: Interaction):
    if interaction.type == discord.InteractionType.component and interaction.data["custom_id"] == "join_button":
        giveaway = giveaways.get(interaction.message.id)
        if not giveaway:
            await interaction.response.send_message("This giveaway has ended or is invalid.", ephemeral=True)
            return

        if giveaway["role_id"]:
            role = discord.utils.get(interaction.guild.roles, id=giveaway["role_id"])
            if role not in interaction.user.roles:
                await interaction.response.send_message(f"You need the role {role.mention} to join!", ephemeral=True)
                return

        if interaction.user.id in giveaway["participants"]:
            await interaction.response.send_message("You already joined!", ephemeral=True)
        else:
            giveaway["participants"].append(interaction.user.id)
            await interaction.response.send_message("You joined the giveaway!", ephemeral=True)

@tasks.loop(minutes=2)
async def giveaway_check():
    now = datetime.utcnow()
    for message_id, data in list(giveaways.items()):
        if now >= data["end_time"]:
            channel = bot.get_channel(data["channel_id"])
            if not channel:
                continue

            try:
                message = await channel.fetch_message(message_id)
            except:
                continue

            participants = data["participants"]
            if not participants:
                await channel.send(f"No one joined the giveaway for **{data['prize']}**.")
            else:
                winner_id = random.choice(participants)
                winner = await bot.fetch_user(winner_id)
                await channel.send(f"🎉 Congratulations {winner.mention}! You won **{data['prize']}**! (Donor: {data['donor']})")

            del giveaways[message_id]

keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
