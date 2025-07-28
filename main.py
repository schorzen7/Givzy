import discord from discord.ext import commands, tasks from discord import app_commands import asyncio import os import random from dotenv import load_dotenv from keep_alive import keep_alive

load_dotenv() TOKEN = os.getenv("DISCORD_TOKEN") GUILD_ID = discord.Object(id=int(os.getenv("GUILD_ID"))) LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))

intents = discord.Intents.default() intents.messages = True intents.guilds = True intents.message_content = True intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents) tree = bot.tree

active_giveaways = {} role_rewards = {} xp_data = {} xp_cooldown = set()

@bot.event async def on_ready(): await tree.sync(guild=GUILD_ID) print(f"Logged in as {bot.user}!")

@tree.command(name="giveaway", description="Start a giveaway.", guild=GUILD_ID) @app_commands.describe(prize="The prize for the giveaway", duration="Duration in seconds", donor="Who is donating the prize", role="Optional role required to join") async def giveaway(interaction: discord.Interaction, prize: str, duration: int, donor: str, role: discord.Role = None): if interaction.channel.id in active_giveaways: await interaction.response.send_message("There's already an ongoing giveaway in this channel.", ephemeral=True) return

embed = discord.Embed(title="🎉 Giveaway Started! 🎉", description=f"**Prize:** {prize}\n**Donor:** {donor}\n**Duration:** {duration} seconds", color=0x00ff00)
embed.set_footer(text="React with 🎉 to enter!")
message = await interaction.channel.send(embed=embed, view=None)

join_button = discord.ui.Button(label="Join 🎉", style=discord.ButtonStyle.green)
cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.red)
reroll_button = discord.ui.Button(label="Reroll", style=discord.ButtonStyle.blurple)

class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.participants = set()

    @discord.ui.button(label="Join 🎉", style=discord.ButtonStyle.green)
    async def join(self, interaction2: discord.Interaction, button: discord.ui.Button):
        if role and role not in interaction2.user.roles:
            await interaction2.response.send_message("You don't have the required role to join.", ephemeral=True)
            return
        if interaction2.user.id in self.participants:
            await interaction2.response.send_message("You already joined the giveaway.", ephemeral=True)
        else:
            self.participants.add(interaction2.user.id)
            await interaction2.response.send_message("You have joined the giveaway! 🎉", ephemeral=True)
            await update_embed()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction2: discord.Interaction, button: discord.ui.Button):
        if interaction2.user.id != interaction.user.id:
            await interaction2.response.send_message("Only the giveaway host can cancel this giveaway.", ephemeral=True)
            return
        await interaction2.response.send_message("Giveaway cancelled.", ephemeral=True)
        await message.delete()
        self.stop()
        active_giveaways.pop(interaction.channel.id, None)

    @discord.ui.button(label="Reroll", style=discord.ButtonStyle.blurple)
    async def reroll(self, interaction2: discord.Interaction, button: discord.ui.Button):
        if interaction2.user.id != interaction.user.id:
            await interaction2.response.send_message("Only the giveaway host can reroll.", ephemeral=True)
            return
        if not self.participants:
            await interaction2.response.send_message("No participants to reroll.", ephemeral=True)
            return
        winner_id = random.choice(list(self.participants))
        winner = interaction.guild.get_member(winner_id)
        await interaction.channel.send(f"🎉 The new winner is {winner.mention}! Congratulations!")

view = GiveawayView()
await message.edit(view=view)
active_giveaways[interaction.channel.id] = view

async def update_embed():
    embed.description = f"**Prize:** {prize}\n**Donor:** {donor}\n**Duration:** {duration} seconds\n**Participants:** {len(view.participants)}"
    await message.edit(embed=embed)

await interaction.response.send_message("Giveaway started!", ephemeral=True)

for remaining in range(duration, 0, -1):
    embed.set_footer(text=f"⏳ Ending in {remaining} seconds...")
    await message.edit(embed=embed)
    await asyncio.sleep(1)

if view.participants:
    winner_id = random.choice(list(view.participants))
    winner = interaction.guild.get_member(winner_id)
    await interaction.channel.send(f"🎉 Congratulations {winner.mention}! You won the **{prize}**!")
else:
    await interaction.channel.send("No one joined the giveaway.")

active_giveaways.pop(interaction.channel.id, None)

keep_alive() bot.run(TOKEN)
