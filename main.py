import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
import random
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

TOKEN = os.environ["TOKEN"]
GUILD_ID = discord.Object(id=int(os.environ["GUILD_ID"]))

giveaways = {}
role_rewards = {}

@bot.event
async def on_ready():
    await tree.sync(guild=GUILD_ID)
    print(f"Logged in as {bot.user}")
    keep_alive()
    
@tree.command(name="giveaway", description="Start a giveaway", guild=GUILD_ID)
@app_commands.describe(prize="What is the prize?",
                       duration="How long? (in seconds)",
                       donor="Who donated the prize?",
                       required_role="Optional: Role required to join")
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str, required_role: discord.Role = None):
    if interaction.channel_id in giveaways:
        await interaction.response.send_message("A giveaway is already running in this channel.", ephemeral=True)
        return

    embed = discord.Embed(title="🎉 Giveaway Started!", description=f"**Prize:** {prize}\n**Donor:** {donor}\n**Time Remaining:** {duration} seconds\n\nClick **Join** below to enter!", color=discord.Color.green())
    embed.set_footer(text="Ends soon!")
    embed.add_field(name="Participants", value="0")

    view = discord.ui.View()
    participants = set()

    async def update_embed():
        try:
            while duration > 0:
                embed.set_field_at(0, name="Participants", value=str(len(participants)))
                embed.description = f"**Prize:** {prize}\n**Donor:** {donor}\n**Time Remaining:** {duration} seconds\n\nClick **Join** below to enter!"
                await message.edit(embed=embed, view=view)
                await asyncio.sleep(1)
                nonlocal duration
                duration -= 1
        except Exception:
            pass

    class JoinButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="🎉 Join", style=discord.ButtonStyle.green)

        async def callback(self, interaction2: discord.Interaction):
            if required_role and required_role not in interaction2.user.roles:
                await interaction2.response.send_message("You don't have the required role to join this giveaway.", ephemeral=True)
                return
            if interaction2.user.id in participants:
                await interaction2.response.send_message("You already joined!", ephemeral=True)
                return
            participants.add(interaction2.user.id)
            await interaction2.response.send_message("You've entered the giveaway!", ephemeral=True)

    class CancelButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="❌ Cancel", style=discord.ButtonStyle.red)

        async def callback(self, interaction2: discord.Interaction):
            if interaction2.user != interaction.user:
                await interaction2.response.send_message("Only the giveaway creator can cancel.", ephemeral=True)
                return
            giveaways.pop(interaction.channel_id, None)
            await message.edit(content="❌ This giveaway was cancelled.", embed=None, view=None)

    class RerollButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="🔁 Reroll", style=discord.ButtonStyle.blurple)

        async def callback(self, interaction2: discord.Interaction):
            if interaction2.user != interaction.user:
                await interaction2.response.send_message("Only the giveaway creator can reroll.", ephemeral=True)
                return
            if participants:
                winner_id = random.choice(list(participants))
                winner = await bot.fetch_user(winner_id)
                await interaction.channel.send(f"🎉 New rerolled winner: {winner.mention} for **{prize}**!")
            else:
                await interaction.channel.send("❌ No participants to reroll.")

    view.add_item(JoinButton())
    view.add_item(CancelButton())
    view.add_item(RerollButton())

    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()
    giveaways[interaction.channel_id] = True

    await update_embed()

    giveaways.pop(interaction.channel_id, None)
    if participants:
        winner_id = random.choice(list(participants))
        winner = await bot.fetch_user(winner_id)
        await interaction.channel.send(f"🎉 Congratulations {winner.mention}, you won **{prize}**!")
    else:
        await interaction.channel.send("😢 No one joined the giveaway.")

bot.run(TOKEN)
