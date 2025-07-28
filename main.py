import discord from discord.ext import commands from discord import app_commands from discord.ui import View, Button import asyncio import os import json from datetime import datetime, timedelta from keep_alive import keep_alive

intents = discord.Intents.default() intents.message_content = True bot = commands.Bot(command_prefix="/", intents=intents) tree = bot.tree

TOKEN = os.getenv("DISCORD_TOKEN")

giveaways = {} DATA_FILE = "data.json"

def load_data(): try: with open(DATA_FILE, "r") as f: return json.load(f) except (FileNotFoundError, json.JSONDecodeError): return {}

def save_data(data): with open(DATA_FILE, "w") as f: json.dump(data, f, indent=4)

@bot.event async def on_ready(): global giveaways giveaways = load_data() await tree.sync() print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

class JoinButton(View): def init(self, message_id): super().init(timeout=None) self.message_id = message_id

@discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green)
async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
    giveaway_data = giveaways.get(str(self.message_id))
    if giveaway_data is None:
        return await interaction.response.send_message("This giveaway no longer exists.", ephemeral=True)

    if interaction.user.id in giveaway_data["participants"]:
        return await interaction.response.send_message("You've already joined this giveaway!", ephemeral=True)

    giveaway_data["participants"].append(interaction.user.id)
    save_data(giveaways)
    await interaction.response.send_message("You have joined the giveaway!", ephemeral=True)

@discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red)
async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
    giveaway_data = giveaways.get(str(self.message_id))
    if giveaway_data is None:
        return await interaction.response.send_message("This giveaway no longer exists.", ephemeral=True)

    if interaction.user.id not in giveaway_data["participants"]:
        return await interaction.response.send_message("You are not in this giveaway!", ephemeral=True)

    giveaway_data["participants"].remove(interaction.user.id)
    save_data(giveaways)
    await interaction.response.send_message("You have been removed from the giveaway.", ephemeral=True)

async def countdown(message, duration, embed): message_id = str(message.id) end_time = datetime.utcnow() + timedelta(seconds=duration)

while datetime.utcnow() < end_time:
    remaining = int((end_time - datetime.utcnow()).total_seconds())
    embed.set_field_at(0, name="⏰ Ends In", value=f"<t:{int(end_time.timestamp())}:R>", inline=False)
    embed.set_footer(text=f"Participants: {len(giveaways[message_id]['participants'])}")
    try:
        await message.edit(embed=embed, view=JoinButton(message_id))
    except discord.NotFound:
        return
    await asyncio.sleep(1)

@app_commands.command(name="giveaway") @app_commands.describe(prize="The prize to be given away", duration="Duration in seconds", donor="Name of the giveaway donor") async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str): if not interaction.user.guild_permissions.manage_guild: return await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)

embed = discord.Embed(title="🎉 Giveaway Started! 🎉", color=discord.Color.purple())
embed.add_field(name="⏰ Ends In", value=f"<t:{int((datetime.utcnow() + timedelta(seconds=duration)).timestamp())}:R>", inline=False)
embed.add_field(name="🏆 Prize", value=prize, inline=True)
embed.add_field(name="🎁 Donor", value=donor, inline=True)
embed.set_footer(text="Participants: 0")

message = await interaction.channel.send(embed=embed, view=JoinButton(None))
view = JoinButton(message.id)
await message.edit(view=view)

giveaways[str(message.id)] = {
    "participants": [],
    "prize": prize,
    "donor": donor,
    "ended": False
}
save_data(giveaways)

await interaction.response.send_message("Giveaway started!", ephemeral=True)
await countdown(message, duration, embed)
await end_giveaway(message)

async def end_giveaway(message): message_id = str(message.id) giveaway_data = giveaways.get(message_id) if not giveaway_data or giveaway_data["ended"]: return

participants = giveaway_data["participants"]
prize = giveaway_data["prize"]

if not participants:
    result_embed = discord.Embed(title="🎉 Giveaway Ended! 🎉", description="No participants joined the giveaway.", color=discord.Color.red())
else:
    winner_id = participants[0] if len(participants) == 1 else random.choice(participants)
    winner = f"<@{winner_id}>"
    result_embed = discord.Embed(title="🎉 Giveaway Ended! 🎉", description=f"Congratulations {winner}, you won **{prize}**!", color=discord.Color.green())

giveaway_data["ended"] = True
save_data(giveaways)

await message.edit(embed=result_embed, view=None)

keep_alive() bot.run(TOKEN)
