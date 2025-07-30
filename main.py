import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random
import os
import json
import time  # 🔸 Added for cooldown tracking
from datetime import datetime, timedelta, timezone
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Load existing giveaway data
if os.path.exists("data.json"):
    with open("data.json", "r") as f:
        giveaways = json.load(f)
else:
    giveaways = {}

def save_data():
    with open("data.json", "w") as f:
        json.dump(giveaways, f, indent=4)

join_cooldowns = {}  # 🔸 Global cooldown dictionary

class JoinButton(discord.ui.View):
    def __init__(self, message_id):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.success, custom_id="join_button")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        now = time.time()
        last_used = join_cooldowns.get(user_id, 0)

        if now - last_used < 10:
            remaining = int(10 - (now - last_used))
            await interaction.response.send_message(
                f"⏳ Please wait `{remaining}` seconds before trying again.",
                ephemeral=True
            )
            return
        join_cooldowns[user_id] = now  # 🔸 Record last use time

        giveaway_data = giveaways.get(str(self.message_id))
        if giveaway_data:
            required_role_id = giveaway_data.get("required_role")
            if required_role_id:
                required_role = interaction.guild.get_role(required_role_id)
                if required_role not in interaction.user.roles:
                    await interaction.response.send_message(
                        f"You need the role **{required_role.name}** to join this giveaway.",
                        ephemeral=True
                    )
                    return

            if interaction.user.id in giveaway_data["participants"]:
                await interaction.response.send_message("You already joined the giveaway!", ephemeral=True)
            else:
                giveaway_data["participants"].append(interaction.user.id)
                save_data()
                await interaction.response.send_message("You've joined the giveaway!", ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger, custom_id="cancel_button")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway_data = giveaways.get(str(self.message_id))
        if giveaway_data and interaction.user.id in giveaway_data["participants"]:
            giveaway_data["participants"].remove(interaction.user.id)
            save_data()
            await interaction.response.send_message("You left the giveaway.", ephemeral=True)
        else:
            await interaction.response.send_message("You are not in the giveaway.", ephemeral=True)

    @discord.ui.button(label="🔁 Reroll", style=discord.ButtonStyle.secondary, custom_id="reroll_button")
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway_data = giveaways.get(str(self.message_id))
        if giveaway_data and interaction.user.guild_permissions.manage_messages:
            message = await interaction.channel.fetch_message(interaction.message.id)
            await end_giveaway(message, message.embeds[0], giveaway_data, reroll=True)
            await interaction.response.send_message("Rerolled the giveaway!", ephemeral=True)
        else:
            await interaction.response.send_message("You don't have permission to reroll.", ephemeral=True)

async def simple_wait(duration, message, embed, giveaway_data):
    await asyncio.sleep(duration)
    await end_giveaway(message, embed, giveaway_data)

async def end_giveaway(message, embed, giveaway_data, reroll=False):
    participants = giveaway_data["participants"]
    if not participants:
        embed.color = discord.Color.red()
        embed.set_footer(text="Giveaway ended. No participants.")
        await message.edit(embed=embed, view=None)
        return

    winner_id = random.choice(participants)
    winner = message.guild.get_member(winner_id)

    embed.color = discord.Color.green()
    embed.set_footer(text="Giveaway ended!")
    embed.add_field(name="🎉 Winner", value=f"{winner.mention if winner else 'Unknown User'}", inline=False)
    await message.edit(embed=embed, view=None)

    try:
        await message.channel.send(f"🎉 Congratulations {winner.mention if winner else 'Unknown User'}! You won **{giveaway_data['prize']}**!")
    except Exception as e:
        print(f"Failed to announce winner: {e}")

    if not reroll:
        giveaways.pop(str(message.id), None)
        save_data()

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    prize="The giveaway prize",
    duration="Duration in seconds",
    donor="Who is giving this prize?",
    role="Optional role required to join"
)
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str, role: discord.Role = None):
    end_time = datetime.now(timezone.utc) + timedelta(seconds=duration)
    end_timestamp = int(end_time.timestamp())
    timestamp_str = f"<t:{end_timestamp}:F>"

    description = f"**Prize:** {prize}\n**Donor:** {donor}\n**Ends:** {timestamp_str}"
    if role:
        description += f"\n**Role Required:** {role.mention}"

    embed = discord.Embed(
        title="🎉 Giveaway",
        description=description,
        color=discord.Color.purple()
    )
    embed.set_footer(text="Waiting for participants...")
    view = JoinButton(message_id=None)

    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()

    view.message_id = message.id
    giveaways[str(message.id)] = {
        "participants": [],
        "prize": prize,
        "donor": donor,
        "end_time": end_timestamp,
        "required_role": role.id if role else None
    }
    save_data()

    await simple_wait(duration, message, embed, giveaways[str(message.id)])

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
