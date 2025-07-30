import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
giveaways = {}

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    check_giveaways.start()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

def format_time_remaining(delta):
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"

@bot.tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    prize="The prize of the giveaway",
    duration="Duration in seconds (e.g., 60 for 1 min, 3600 for 1 hour)",
    role_requirement="Role required to join (optional)",
    donor="The donor of the prize (optional)"
)
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, role_requirement: discord.Role = None, donor: str = None):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("You don't have permission to start giveaways.", ephemeral=True)
        return

    end_time = datetime.utcnow() + timedelta(seconds=duration)

    embed = discord.Embed(
        title="🎉 New Giveaway!",
        description=f"**Prize:** {prize}\n"
                    f"**Ends:** <t:{int(end_time.timestamp())}:F>\n"
                    f"**Hosted by:** {interaction.user.mention}\n"
                    + (f"**Role Required:** {role_requirement.mention}\n" if role_requirement else "") 
                    + (f"**Donor:** {donor}\n" if donor else ""),
        color=discord.Color.gold()
    )
    embed.set_footer(text="Click the button below to enter!")
    
    join_button = discord.ui.Button(label="🎉 Join", style=discord.ButtonStyle.green, custom_id="join")
    cancel_button = discord.ui.Button(label="❌ Cancel", style=discord.ButtonStyle.danger, custom_id="cancel")

    class GiveawayView(discord.ui.View):
        def __init__(self, timeout=None):
            super().__init__(timeout=timeout)
            self.join_button = join_button
            self.cancel_button = cancel_button
            self.add_item(join_button)
            self.add_item(cancel_button)

        @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green, custom_id="join")
        async def join(self, interaction_button: discord.Interaction, button: discord.ui.Button):
            data = giveaways.get(message.id)
            if not data:
                await interaction_button.response.send_message("This giveaway no longer exists.", ephemeral=True)
                return
            if role_requirement and role_requirement not in interaction_button.user.roles:
                await interaction_button.response.send_message("You don't have the required role to join this giveaway.", ephemeral=True)
                return
            if interaction_button.user.id in data["participants"]:
                await interaction_button.response.send_message("You've already joined!", ephemeral=True)
            else:
                data["participants"].append(interaction_button.user.id)
                await interaction_button.response.send_message("Successfully entered!", ephemeral=True)

        @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger, custom_id="cancel")
        async def cancel(self, interaction_button: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != interaction_button.user.id and not interaction_button.user.guild_permissions.manage_messages:
                await interaction_button.response.send_message("Only the host or a moderator can cancel this giveaway.", ephemeral=True)
                return
            giveaways.pop(message.id, None)
            await message.edit(content="❌ This giveaway has been cancelled.", embed=None, view=None)
            await interaction_button.response.send_message("Giveaway cancelled.", ephemeral=True)

    view = GiveawayView(timeout=None)
    message = await interaction.channel.send(embed=embed, view=view)

    giveaways[message.id] = {
        "prize": prize,
        "end_time": end_time,
        "channel_id": interaction.channel.id,
        "message_id": message.id,
        "host_id": interaction.user.id,
        "participants": [],
        "role_requirement": role_requirement.id if role_requirement else None,
        "donor": donor
    }

    await interaction.response.send_message("Giveaway started!", ephemeral=True)

@tasks.loop(minutes=2)
async def check_giveaways():
    now = datetime.utcnow()
    to_remove = []

    for message_id, data in giveaways.items():
        if now >= data["end_time"]:
            channel = bot.get_channel(data["channel_id"])
            try:
                message = await channel.fetch_message(message_id)
            except:
                continue
            view = discord.ui.View()
            view.clear_items()
            await message.edit(content="🎉 Giveaway ended!", view=view)

            if data["participants"]:
                winner_id = random.choice(data["participants"])
                winner = await bot.fetch_user(winner_id)
                await channel.send(f"🎉 Congratulations {winner.mention}, you won **{data['prize']}**!")
            else:
                await channel.send("No one joined the giveaway.")

            to_remove.append(message_id)

    for mid in to_remove:
        giveaways.pop(mid, None)

keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
