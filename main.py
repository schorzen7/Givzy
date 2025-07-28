import discord from discord.ext import commands, tasks from discord import app_commands import asyncio import os import random import time from dotenv import load_dotenv from keep_alive import keep_alive

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN") GUILD_ID = discord.Object(id=int(os.getenv("GUILD_ID")))

intents = discord.Intents.default() intents.message_content = True bot = commands.Bot(command_prefix="!", intents=intents) tree = bot.tree

giveaways = {}

class GiveawayView(discord.ui.View): def init(self, message_id): super().init(timeout=None) self.message_id = message_id

@discord.ui.button(label="🎉 Join Giveaway", style=discord.ButtonStyle.green, custom_id="join_button")
async def join_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
    giveaway = giveaways.get(self.message_id)
    if giveaway is None:
        return await interaction.response.send_message("This giveaway has ended or doesn't exist.", ephemeral=True)

    if interaction.user.id in giveaway["participants"]:
        return await interaction.response.send_message("You've already joined this giveaway!", ephemeral=True)

    if giveaway["required_role"] and giveaway["required_role"] not in [role.id for role in interaction.user.roles]:
        return await interaction.response.send_message("You don't have the required role to join this giveaway.", ephemeral=True)

    giveaway["participants"].append(interaction.user.id)
    await interaction.response.send_message("You've successfully joined the giveaway! 🎉", ephemeral=True)

@discord.ui.button(label="❌ Cancel Giveaway", style=discord.ButtonStyle.red, custom_id="cancel_button")
async def cancel_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
    giveaway = giveaways.get(self.message_id)
    if giveaway is None:
        return await interaction.response.send_message("This giveaway has already ended or doesn't exist.", ephemeral=True)

    if interaction.user.id != giveaway["donor"]:
        return await interaction.response.send_message("Only the giveaway host can cancel this giveaway.", ephemeral=True)

    giveaways.pop(self.message_id)
    await interaction.message.edit(content="❌ Giveaway cancelled.", embed=None, view=None)
    await interaction.response.send_message("You cancelled the giveaway.", ephemeral=True)

@discord.ui.button(label="🔁 Reroll Winner", style=discord.ButtonStyle.blurple, custom_id="reroll_button")
async def reroll_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
    giveaway = giveaways.get(self.message_id)
    if not giveaway:
        return await interaction.response.send_message("Giveaway not found or has ended.", ephemeral=True)

    if not giveaway["participants"]:
        return await interaction.response.send_message("No participants to reroll.", ephemeral=True)

    winner_id = random.choice(giveaway["participants"])
    winner = await bot.fetch_user(winner_id)
    await interaction.response.send_message(f"🔁 New winner is {winner.mention}! 🎉", ephemeral=False)

@tree.command(name="giveaway", description="Start a giveaway") @app_commands.describe( prize="The giveaway prize", duration="Duration in seconds", required_role="Role required to join (optional)" ) async def giveaway(interaction: discord.Interaction, prize: str, duration: int, required_role: discord.Role = None): await interaction.response.defer() end_time = time.time() + duration

embed = discord.Embed(title="🎉 Giveaway! 🎉", description=prize, color=discord.Color.green())
embed.add_field(name="Hosted by", value=interaction.user.mention, inline=False)
embed.add_field(name="⏳ Time Left", value=f"`{duration // 60:02d}:{duration % 60:02d}`", inline=False)
embed.add_field(name="👥 Participants", value="0", inline=False)
if required_role:
    embed.add_field(name="Required Role", value=required_role.mention, inline=False)

view = GiveawayView(message_id=None)
message = await interaction.followup.send(embed=embed, view=view)

giveaways[message.id] = {
    "prize": prize,
    "end_time": end_time,
    "participants": [],
    "donor": interaction.user.id,
    "required_role": required_role.id if required_role else None,
    "message": message
}

view.message_id = message.id
message_id = message.id

async def update_countdown():
    while True:
        remaining = int(end_time - time.time())
        if remaining <= 0:
            break
        minutes, seconds = divmod(remaining, 60)
        embed.set_field_at(1, name="⏳ Time Left", value=f"`{minutes:02d}:{seconds:02d}`", inline=False)
        embed.set_field_at(2, name="👥 Participants", value=str(len(giveaways[message_id]["participants"])), inline=False)
        await message.edit(embed=embed)
        await asyncio.sleep(1)

asyncio.create_task(update_countdown())

await asyncio.sleep(duration)

giveaway = giveaways.pop(message.id, None)
if giveaway is None:
    return

if not giveaway["participants"]:
    await message.edit(content="😢 Giveaway ended. No participants.", embed=None, view=None)
else:
    winner_id = random.choice(giveaway["participants"])
    winner = await bot.fetch_user(winner_id)
    await message.edit(content=f"🎉 Congratulations {winner.mention}! You won **{prize}**!", embed=None, view=None)

@tree.command(name="cancel", description="Cancel a giveaway by message ID") @app_commands.describe(message_id="Message ID of the giveaway to cancel") async def cancel(interaction: discord.Interaction, message_id: str): try: message_id = int(message_id) except ValueError: return await interaction.response.send_message("Invalid message ID.", ephemeral=True)

giveaway = giveaways.pop(message_id, None)
if not giveaway:
    return await interaction.response.send_message("Giveaway not found or already ended.", ephemeral=True)

await giveaway["message"].edit(content="❌ Giveaway cancelled.", embed=None, view=None)
await interaction.response.send_message("Giveaway cancelled successfully.", ephemeral=True)

@tree.command(name="reroll", description="Reroll a giveaway winner by message ID") @app_commands.describe(message_id="Message ID of the giveaway to reroll") async def reroll(interaction: discord.Interaction, message_id: str): try: message_id = int(message_id) except ValueError: return await interaction.response.send_message("Invalid message ID.", ephemeral=True)

giveaway = giveaways.get(message_id)
if not giveaway:
    return await interaction.response.send_message("Giveaway not found or has ended.", ephemeral=True)

if not giveaway["participants"]:
    return await interaction.response.send_message("No participants to reroll.", ephemeral=True)

winner_id = random.choice(giveaway["participants"])
winner = await bot.fetch_user(winner_id)
await interaction.response.send_message(f"🔁 New winner is {winner.mention}! 🎉", ephemeral=False)

@bot.event async def on_ready(): await tree.sync(guild=GUILD_ID) print(f"Logged in as {bot.user}")

keep_alive() bot.run(TOKEN)
