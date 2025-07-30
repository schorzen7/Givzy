import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random
import json
from datetime import datetime, timedelta
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

GUILD_ID = discord.Object(id=YOUR_GUILD_ID)  # Replace with your actual server ID

giveaways = {}

# Load giveaways from file
def load_data():
    global giveaways
    if os.path.exists("data.json"):
        with open("data.json", "r") as f:
            giveaways = json.load(f)

# Save giveaways to file
def save_data():
    with open("data.json", "w") as f:
        json.dump(giveaways, f, indent=4)

# Button class for joining giveaways
class JoinButton(discord.ui.View):
    def __init__(self, message_id, role_id=None):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.role_id = role_id
        self.cooldowns = {}  # cooldown tracking

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green, custom_id="join_button")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        now = datetime.utcnow().timestamp()

        # Cooldown system
        last_used = self.cooldowns.get(user_id, 0)
        if now - last_used < 10:
            await interaction.response.send_message("⏳ Please wait before clicking again!", ephemeral=True)
            return
        self.cooldowns[user_id] = now

        giveaway = giveaways.get(self.message_id)
        if not giveaway:
            await interaction.response.send_message("⚠️ This giveaway is no longer active.", ephemeral=True)
            return

        if self.role_id:
            role = interaction.guild.get_role(self.role_id)
            if role not in interaction.user.roles:
                await interaction.response.send_message(f"🔒 You must have the role {role.mention} to join this giveaway!", ephemeral=True)
                return

        if interaction.user.id in giveaway['participants']:
            await interaction.response.send_message("✅ You already joined this giveaway!", ephemeral=True)
            return

        giveaway['participants'].append(interaction.user.id)
        save_data()

        await interaction.response.send_message("🎉 You joined the giveaway!", ephemeral=True)

# Giveaway checker (runs in background)
async def giveaway_checker():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.utcnow().timestamp()
        to_remove = []

        for msg_id, giveaway in list(giveaways.items()):
            if now >= giveaway['end_time']:
                try:
                    channel = bot.get_channel(giveaway['channel_id'])
                    message = await channel.fetch_message(giveaway['message_id'])
                    participants = giveaway['participants']

                    if participants:
                        winner_id = random.choice(participants)
                        winner = await bot.fetch_user(winner_id)
                        await channel.send(f"🎉 Congratulations {winner.mention}! You won the giveaway: **{giveaway['prize']}**")
                    else:
                        await channel.send(f"No one participated in the giveaway for **{giveaway['prize']}** 😢")
                    
                    to_remove.append(msg_id)
                except Exception as e:
                    print(f"Error finalizing giveaway {msg_id}: {e}")
                    to_remove.append(msg_id)

        for msg_id in to_remove:
            giveaways.pop(msg_id, None)
        save_data()

        await asyncio.sleep(60)

# Slash command to create a giveaway
@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    duration="Duration in seconds",
    prize="Prize of the giveaway",
    role="Optional role required to join"
)
async def giveaway(interaction: discord.Interaction, duration: int, prize: str, role: discord.Role = None):
    await interaction.response.defer(ephemeral=True)

    end_time = datetime.utcnow().timestamp() + duration
    full_date = datetime.utcnow() + timedelta(seconds=duration)
    end_time_str = full_date.strftime("%A, %B %d, %Y at %I:%M %p UTC")

    embed = discord.Embed(
        title="🎉 New Giveaway!",
        description=f"**Prize:** {prize}\n"
                    f"**Ends:** {end_time_str}",
        color=discord.Color.random()
    )
    embed.set_footer(text="Click the button to join!")

    view = JoinButton(message_id=None, role_id=role.id if role else None)
    message = await interaction.channel.send(embed=embed, view=view)

    view.message_id = str(message.id)

    giveaways[str(message.id)] = {
        "channel_id": interaction.channel.id,
        "message_id": message.id,
        "end_time": end_time,
        "prize": prize,
        "participants": [],
        "required_role": role.id if role else None
    }

    save_data()

    await interaction.followup.send(f"✅ Giveaway for **{prize}** started in {interaction.channel.mention}!", ephemeral=True)

# Reroll command
@tree.command(name="reroll", description="Reroll the giveaway winner")
@app_commands.describe(message_id="Message ID of the giveaway")
async def reroll(interaction: discord.Interaction, message_id: str):
    if message_id not in giveaways:
        await interaction.response.send_message("⚠️ Giveaway not found!", ephemeral=True)
        return

    participants = giveaways[message_id]['participants']
    prize = giveaways[message_id]['prize']

    if not participants:
        await interaction.response.send_message("❌ No participants to reroll.", ephemeral=True)
        return

    winner_id = random.choice(participants)
    winner = await bot.fetch_user(winner_id)

    await interaction.response.send_message(f"🔁 New winner: {winner.mention} for **{prize}**!", ephemeral=False)

# Cancel command
@tree.command(name="cancel", description="Cancel a giveaway")
@app_commands.describe(message_id="Message ID of the giveaway")
async def cancel(interaction: discord.Interaction, message_id: str):
    if message_id not in giveaways:
        await interaction.response.send_message("⚠️ Giveaway not found!", ephemeral=True)
        return

    del giveaways[message_id]
    save_data()

    await interaction.response.send_message("❌ Giveaway has been cancelled.", ephemeral=True)

# Start-up tasks
@bot.event
async def on_ready():
    load_data()
    print(f"Logged in as {bot.user}")
    bot.loop.create_task(giveaway_checker())

    # Reconnect buttons
    for msg_id, data in giveaways.items():
        view = JoinButton(message_id=msg_id, role_id=data.get("required_role"))
        try:
            channel = bot.get_channel(data['channel_id'])
            message = await channel.fetch_message(int(msg_id))
            await message.edit(view=view)
        except Exception as e:
            print(f"Error restoring button for message {msg_id}: {e}")

keep_alive()
TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
