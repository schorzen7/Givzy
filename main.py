import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button
import asyncio
import os
from datetime import datetime, timedelta, timezone
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = False
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

GUILD_ID = discord.Object(id=int(os.environ["GUILD_ID"]))

giveaways = {}
cooldowns = {}

class JoinView(View):
    def __init__(self, message_id):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green, custom_id="join_giveaway")
    async def join(self, interaction: discord.Interaction, button: Button):
        user = interaction.user
        now = datetime.now()

        if user.id in cooldowns and (now - cooldowns[user.id]).total_seconds() < 10:
            await interaction.response.send_message("⏳ Please wait 10 seconds before clicking again.", ephemeral=True)
            return

        cooldowns[user.id] = now
        giveaway = giveaways.get(self.message_id)
        if not giveaway:
            await interaction.response.send_message("❌ This giveaway no longer exists.", ephemeral=True)
            return

        if giveaway["role"] and giveaway["role"] not in [role.id for role in user.roles]:
            await interaction.response.send_message("🚫 You don't have the required role to join this giveaway.", ephemeral=True)
            return

        if user.id in giveaway["participants"]:
            await interaction.response.send_message("❌ You already joined this giveaway.", ephemeral=True)
        else:
            giveaway["participants"].append(user.id)
            await interaction.response.send_message("✅ You joined the giveaway!", ephemeral=True)
            await update_embed(interaction.message, giveaway)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red, custom_id="cancel_giveaway")
    async def cancel(self, interaction: discord.Interaction, button: Button):
        user = interaction.user
        giveaway = giveaways.get(self.message_id)
        if not giveaway:
            await interaction.response.send_message("❌ This giveaway no longer exists.", ephemeral=True)
            return
        if user.id in giveaway["participants"]:
            giveaway["participants"].remove(user.id)
            await interaction.response.send_message("✅ You left the giveaway.", ephemeral=True)
            await update_embed(interaction.message, giveaway)
        else:
            await interaction.response.send_message("❌ You're not part of this giveaway.", ephemeral=True)

async def update_embed(message, giveaway):
    embed = discord.Embed(
        title="🎁 Giveaway",
        description=f"**Prize:** {giveaway['prize']}\n"
                    f"**Donor:** {giveaway['donor'].mention}\n"
                    f"**Ends At:** {giveaway['end_time'].strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                    f"**Participants:** {len(giveaway['participants'])}",
        color=discord.Color.blurple()
    )
    await message.edit(embed=embed)

@tree.command(name="giveaway", description="Start a giveaway", guild=GUILD_ID)
@app_commands.describe(
    prize="Prize of the giveaway",
    duration="Duration in seconds",
    role_requirement="Optional role required to join"
)
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, role_requirement: discord.Role = None):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    end_time = datetime.now(timezone.utc) + timedelta(seconds=duration)
    embed = discord.Embed(
        title="🎁 Giveaway",
        description=f"**Prize:** {prize}\n"
                    f"**Donor:** {interaction.user.mention}\n"
                    f"**Ends At:** {end_time.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                    f"**Participants:** 0",
        color=discord.Color.blurple()
    )

    view = JoinView(message_id=None)
    message = await interaction.channel.send(embed=embed, view=view)
    view.message_id = message.id

    giveaways[message.id] = {
        "prize": prize,
        "end_time": end_time,
        "donor": interaction.user,
        "participants": [],
        "message": message,
        "role": role_requirement.id if role_requirement else None
    }

    await interaction.response.send_message(f"✅ Giveaway started for **{prize}**!", ephemeral=True)

    await asyncio.sleep(duration)

    giveaway = giveaways.pop(message.id, None)
    if giveaway and giveaway["participants"]:
        winner_id = random.choice(giveaway["participants"])
        winner = interaction.guild.get_member(winner_id)
        if winner:
            await interaction.channel.send(f"🎉 Congratulations {winner.mention}, you won **{giveaway['prize']}**!")
        else:
            await interaction.channel.send("⚠️ Winner not found.")
    else:
        await interaction.channel.send("😕 No one joined the giveaway.")

@bot.event
async def on_ready():
    await tree.sync(guild=GUILD_ID)
    print(f"Logged in as {bot.user}.")

keep_alive()
bot.run(os.environ["TOKEN"])
