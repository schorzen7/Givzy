import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Button, View
import os
import random
import asyncio
import re
from keep_alive import keep_alive  # Keep-alive added here

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    application_id=os.getenv("APPLICATION_ID")
)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"❌ Sync failed: {e}")

def parse_duration(duration_str):
    match = re.match(r'^(\d+)([hms])$', duration_str.lower())
    if not match:
        return None
    value, unit = match.groups()
    value = int(value)
    if unit == 'h':
        return value * 3600
    elif unit == 'm':
        return value * 60
    elif unit == 's':
        return value
    return None

@bot.tree.command(name="giveaway", description="Create a giveaway with prize, duration, donor, and optional role requirement.")
@app_commands.describe(
    prize="Giveaway prize",
    duration="Duration (e.g., 1h, 30m)",
    name="Donor name or who donated",
    role="(Optional) Role required to join"
)
@app_commands.checks.has_permissions(manage_messages=True)
async def giveaway(
    interaction: discord.Interaction,
    prize: str,
    duration: str,
    name: str,
    role: discord.Role | None = None
):
    seconds = parse_duration(duration)
    if seconds is None:
        await interaction.response.send_message("❌ Invalid duration format. Use formats like 1h, 30m, or 45s.", ephemeral=True)
        return

    view = GiveawayView(required_role=role)
    embed = discord.Embed(
        title="🎉 Giveaway Started!",
        description=(f"**Prize:** {prize}\n"
                     f"**Duration:** {duration}\n"
                     f"**Donated by:** {name}\n"
                     f"{f'**Requirement:** {role.mention}' if role else ''}"),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()

    view.message_id = message.id
    view.guild_id = interaction.guild.id if interaction.guild else None

    await asyncio.sleep(seconds)

    if view.cancelled:
        return

    if not view.joined_users:
        await message.edit(content="⚠️ Giveaway ended. No one joined!", embed=None, view=None)
        return

    winner_id = random.choice(list(view.joined_users))
    guild = interaction.guild
    winner = guild.get_member(winner_id) if guild else None

    if winner:
        await message.edit(content=f"🎉 Giveaway Ended! Congratulations {winner.mention}!\n**Prize:** {prize}", embed=None, view=None)
    else:
        await message.edit(content="⚠️ Giveaway ended, but the winner could not be found.", embed=None, view=None)

class GiveawayView(View):
    def __init__(self, required_role: discord.Role | None = None):
        super().__init__(timeout=None)
        self.joined_users = set()
        self.cancelled = False
        self.required_role = required_role
        self.message_id = None
        self.guild_id = None
        self.add_item(GiveawayJoinButton(self))
        self.add_item(CancelButton(self))
        self.add_item(RerollButton(self))

class GiveawayJoinButton(Button):
    def __init__(self, parent_view: GiveawayView):
        super().__init__(label="🎉 Join Giveaway", style=discord.ButtonStyle.green)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.cancelled:
            await interaction.response.send_message("🚫 This giveaway was cancelled.", ephemeral=True)
            return

        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("⚠️ This command must be used in a server.", ephemeral=True)
            return

        member = guild.get_member(interaction.user.id)
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("⚠️ Couldn't retrieve your member information.", ephemeral=True)
            return

        if self.parent_view.required_role and self.parent_view.required_role not in member.roles:
            await interaction.response.send_message(f"🚫 You must have the {self.parent_view.required_role.mention} role to join.", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id in self.parent_view.joined_users:
            await interaction.response.send_message("❗ You already joined this giveaway.", ephemeral=True)
        else:
            self.parent_view.joined_users.add(user_id)
            await interaction.response.send_message("✅ You joined the giveaway!", ephemeral=True)

class CancelButton(Button):
    def __init__(self, parent_view: GiveawayView):
        super().__init__(label="❌ Cancel Giveaway", style=discord.ButtonStyle.red)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_messages:
            if interaction.message:
                self.parent_view.cancelled = True
                await interaction.message.edit(content="🚫 Giveaway cancelled by an admin.", view=None)
                await interaction.response.send_message("❌ Giveaway cancelled.", ephemeral=True)
            else:
                await interaction.response.send_message("⚠️ Cannot edit the giveaway message.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ You don’t have permission to cancel this giveaway.", ephemeral=True)

class RerollButton(Button):
    def __init__(self, parent_view: GiveawayView):
        super().__init__(label="🔄 Reroll Winner", style=discord.ButtonStyle.blurple)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_messages:
            if not self.parent_view.joined_users:
                await interaction.response.send_message("⚠️ No users joined the giveaway yet.", ephemeral=True)
                return

            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("⚠️ This command must be used in a server.", ephemeral=True)
                return

            winner_id = random.choice(list(self.parent_view.joined_users))
            winner = guild.get_member(winner_id)
            if winner:
                await interaction.response.send_message(f"🎉 New Winner: {winner.mention}", ephemeral=False)
            else:
                await interaction.response.send_message("⚠️ Couldn't find the selected user.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ You don't have permission to reroll the winner.", ephemeral=True)

# New Command: /cancelgiveaway
@bot.tree.command(name="cancelgiveaway", description="Cancel a giveaway by message ID.")
@app_commands.describe(message_id="The message ID of the giveaway to cancel.")
@app_commands.checks.has_permissions(manage_messages=True)
async def cancel_giveaway(interaction: discord.Interaction, message_id: str):
    try:
        channel = interaction.channel
        message = await channel.fetch_message(int(message_id))
        await message.edit(content="🚫 Giveaway cancelled manually.", view=None)
        await interaction.response.send_message("✅ Giveaway has been cancelled.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to cancel giveaway: {e}", ephemeral=True)

# New Command: /reroll
@bot.tree.command(name="reroll", description="Reroll a giveaway by message ID.")
@app_commands.describe(message_id="The message ID of the giveaway to reroll.")
@app_commands.checks.has_permissions(manage_messages=True)
async def reroll(interaction: discord.Interaction, message_id: str):
    try:
        channel = interaction.channel
        message = await channel.fetch_message(int(message_id))
        view = message.components[0]
        if hasattr(view, "joined_users") and view.joined_users:
            winner_id = random.choice(list(view.joined_users))
            member = interaction.guild.get_member(winner_id)
            if member:
                await interaction.response.send_message(f"🔄 New winner is {member.mention}!", ephemeral=False)
            else:
                await interaction.response.send_message("⚠️ Could not find the new winner.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ No users joined this giveaway.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Reroll failed: {e}", ephemeral=True)

# ✅ Start the web server to keep the bot alive
keep_alive()

# ✅ Run the bot
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ Bot token not found. Please set DISCORD_TOKEN in your environment variables.")
