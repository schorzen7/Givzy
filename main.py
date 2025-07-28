import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
import asyncio
import os
import json
from datetime import datetime, timedelta, timezone
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}  # Store running giveaways: {message.id: {"participants": [], "end_time": datetime}}

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    prize="What is the giveaway prize?",
    duration="Duration in seconds",
    role_requirement="Optional role required to join",
    donor="Name of the sponsor/donor"
)
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str, role_requirement: discord.Role = None):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    end_time = datetime.now(timezone.utc) + timedelta(seconds=duration)

    join_button = Button(label="🎉 Join", style=discord.ButtonStyle.green)
    cancel_button = Button(label="❌ Cancel", style=discord.ButtonStyle.red)

    view = View()
    view.add_item(join_button)
    view.add_item(cancel_button)

    participants = []

    embed = discord.Embed(title="🎁 Giveaway Started!", color=discord.Color.green())
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Donor", value=donor, inline=False)
    embed.add_field(name="Time Remaining", value=f"{duration} seconds", inline=False)
    embed.add_field(name="Participants", value="0", inline=False)
    if role_requirement:
        embed.add_field(name="Required Role", value=role_requirement.mention, inline=False)
    embed.set_footer(text="Giveaway ends soon. Click Join!")

    try:
        message = await interaction.channel.send(embed=embed, view=view)
    except discord.Forbidden:
        await interaction.response.send_message("⚠️ I don't have permission to send messages in this channel.", ephemeral=True)
        return

    await interaction.response.send_message(f"🎉 Giveaway started in {interaction.channel.mention}!", ephemeral=True)

    giveaways[message.id] = {"participants": participants, "end_time": end_time}

    async def countdown():
        while datetime.now(timezone.utc) < end_time:
            remaining = (end_time - datetime.now(timezone.utc)).total_seconds()
            try:
                embed.set_field_at(2, name="Time Remaining", value=f"{int(remaining)} seconds", inline=False)
                embed.set_field_at(3, name="Participants", value=str(len(participants)), inline=False)
                await message.edit(embed=embed, view=view)
            except discord.NotFound:
                break  # Message was deleted
            await asyncio.sleep(1)

        # End giveaway
        view.clear_items()
        try:
            await message.edit(view=view)
        except:
            pass

        if participants:
            winner = random.choice(participants)
            reroll_button = Button(label="🔁 Reroll", style=discord.ButtonStyle.blurple)

            async def reroll_callback(interaction2):
                if not interaction2.user.guild_permissions.manage_guild:
                    await interaction2.response.send_message("You can't reroll this giveaway.", ephemeral=True)
                    return

                new_winner = random.choice(participants)
                await interaction2.response.send_message(f"🔁 New Winner: {new_winner.mention}")

            reroll_button.callback = reroll_callback
            reroll_view = View()
            reroll_view.add_item(reroll_button)

            await interaction.channel.send(f"🎉 Congratulations {winner.mention}, you won **{prize}**!", view=reroll_view)
        else:
            await interaction.channel.send("😢 Giveaway ended with no participants.")

    async def handle_button_click(interaction2):
        if interaction2.custom_id == "join":
            if role_requirement and role_requirement not in interaction2.user.roles:
                await interaction2.response.send_message("You don't have the required role to join.", ephemeral=True)
                return
            if interaction2.user in participants:
                await interaction2.response.send_message("You already joined!", ephemeral=True)
            else:
                participants.append(interaction2.user)
                await interaction2.response.send_message("You're in the giveaway!", ephemeral=True)

        elif interaction2.custom_id == "cancel":
            if interaction2.user.guild_permissions.manage_guild:
                giveaways.pop(message.id, None)
                await interaction2.message.delete()
                await interaction2.response.send_message("❌ Giveaway cancelled.", ephemeral=False)
            else:
                await interaction2.response.send_message("You don't have permission to cancel.", ephemeral=True)

    join_button.custom_id = "join"
    cancel_button.custom_id = "cancel"

    join_button.callback = handle_button_click
    cancel_button.callback = handle_button_click

    bot.loop.create_task(countdown())

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await tree.sync()
        print(f"🔧 Synced {len(synced)} commands")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

keep_alive()
bot.run(os.getenv("TOKEN"))
