import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
import random
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaway_data = {}

class JoinView(discord.ui.View):
    def __init__(self, message_id, role_id):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.role_id = role_id

    @discord.ui.button(label="🎉 Join", style=discord.ButtonStyle.green, custom_id="join_giveaway")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = giveaway_data.get(self.message_id)
        if not giveaway:
            return await interaction.response.send_message("This giveaway no longer exists.", ephemeral=True)

        if self.role_id and self.role_id not in [role.id for role in interaction.user.roles]:
            return await interaction.response.send_message("You don't have the required role to join.", ephemeral=True)

        if interaction.user.id in giveaway["participants"]:
            return await interaction.response.send_message("You've already joined the giveaway!", ephemeral=True)

        giveaway["participants"].add(interaction.user.id)
        await interaction.response.send_message("You've successfully joined the giveaway!", ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red, custom_id="cancel_giveaway")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = giveaway_data.get(self.message_id)
        if not giveaway:
            return await interaction.response.send_message("This giveaway no longer exists.", ephemeral=True)

        if interaction.user.id not in giveaway["participants"]:
            return await interaction.response.send_message("You're not in the giveaway.", ephemeral=True)

        giveaway["participants"].remove(interaction.user.id)
        await interaction.response.send_message("You've been removed from the giveaway.", ephemeral=True)

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(prize="The prize for the giveaway", duration="Duration in seconds", donor="The donor of the giveaway", required_role="Role required to join (optional)")
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str, required_role: discord.Role = None):
    await interaction.response.defer()

    embed = discord.Embed(title="🎉 New Giveaway!", color=discord.Color.purple())
    embed.add_field(name="🎁 Prize", value=prize, inline=False)
    embed.add_field(name="⏱️ Time Remaining", value=f"{duration} seconds", inline=False)
    embed.add_field(name="👤 Donor", value=donor, inline=False)
    if required_role:
        embed.add_field(name="🔒 Required Role", value=required_role.mention, inline=False)
    embed.add_field(name="👥 Participants", value="0", inline=False)
    embed.set_footer(text="Giveaway is active!")
    message = await interaction.followup.send(embed=embed, view=JoinView(message_id=None, role_id=required_role.id if required_role else None))

    giveaway_data[message.id] = {
        "prize": prize,
        "duration": duration,
        "donor": donor,
        "participants": set(),
        "message": message,
        "embed": embed,
        "role": required_role.id if required_role else None
    }

    view = JoinView(message_id=message.id, role_id=required_role.id if required_role else None)
    await message.edit(view=view)

    async def countdown():
        remaining = duration
        while remaining > 0:
            try:
                embed.set_field_at(1, name="⏱️ Time Remaining", value=f"{remaining} seconds", inline=False)
                embed.set_field_at(len(embed.fields) - 1, name="👥 Participants", value=str(len(giveaway_data[message.id]["participants"])), inline=False)
                await message.edit(embed=embed)
                await asyncio.sleep(1)
                remaining -= 1
            except Exception as e:
                print("Countdown error:", e)
                break

        # Giveaway ended
        participants = giveaway_data[message.id]["participants"]
        if not participants:
            embed.title = "❌ Giveaway Cancelled"
            embed.clear_fields()
            embed.description = "Not enough participants to select a winner."
            embed.color = discord.Color.red()
        else:
            winner_id = random.choice(list(participants))
            winner_mention = f"<@{winner_id}>"
            embed.title = "🎉 Giveaway Ended!"
            embed.set_field_at(1, name="⏱️ Time Remaining", value="Ended", inline=False)
            embed.set_field_at(len(embed.fields) - 1, name="👥 Participants", value=str(len(participants)), inline=False)
            embed.add_field(name="🏆 Winner", value=f"{winner_mention}\n🎉 Congratulations!", inline=False)
            embed.color = discord.Color.gold()

        embed.set_footer(text="Giveaway Ended")
        await message.edit(embed=embed, view=None)
        del giveaway_data[message.id]

    bot.loop.create_task(countdown())

@bot.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {bot.user}")

keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
