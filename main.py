import discord from discord.ext import commands, tasks from discord import app_commands import asyncio import os import random from dotenv import load_dotenv from keep_alive import keep_alive

load_dotenv()

intents = discord.Intents.default() intents.messages = True intents.message_content = True intents.guilds = True intents.members = True bot = commands.Bot(command_prefix="!", intents=intents) tree = bot.tree

giveaways = {}

class GiveawayView(discord.ui.View): def init(self, ctx, prize, donor, role, duration): super().init(timeout=None) self.ctx = ctx self.prize = prize self.donor = donor self.role = role self.duration = duration self.entries = set() self.message = None self.guild_id = None self.task = None

@discord.ui.button(label="🎉 Join Giveaway", style=discord.ButtonStyle.success)
async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
    member = interaction.user
    if self.role:
        if self.role not in getattr(member, 'roles', []):
            await interaction.response.send_message(f"You must have the {self.role.mention} role to join this giveaway.", ephemeral=True)
            return
    if member.id in self.entries:
        await interaction.response.send_message("You have already joined the giveaway!", ephemeral=True)
    else:
        self.entries.add(member.id)
        await interaction.response.send_message("You have successfully joined the giveaway! 🎉", ephemeral=True)

async def update_embed(self):
    remaining = int(self.duration.total_seconds())
    while remaining > 0:
        minutes, seconds = divmod(remaining, 60)
        embed = discord.Embed(title="🎉 Giveaway! 🎉", description=f"Prize: **{self.prize}**", color=discord.Color.gold())
        embed.add_field(name="Donated By", value=f"{self.donor}", inline=False)
        embed.add_field(name="Participants", value=f"{len(self.entries)}", inline=False)
        embed.set_footer(text=f"Ends in {minutes}m {seconds}s")
        if self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except:
                pass
        await asyncio.sleep(1)
        remaining -= 1

    await self.end_giveaway()

async def end_giveaway(self):
    if self.entries:
        winner_id = random.choice(list(self.entries))
        guild = bot.get_guild(self.guild_id)
        if guild:
            winner = guild.get_member(winner_id)
            if winner:
                await self.message.channel.send(f"🎉 Congratulations {winner.mention}! You won **{self.prize}**!")
                return
    await self.message.channel.send("No valid entries or winner could not be determined.")

@tree.command(name="giveaway", description="Start a giveaway") @app_commands.describe(prize="Prize for the giveaway", duration="Duration in seconds", name="Who donated this giveaway", role="(Optional) Role required to join") async def giveaway(interaction: discord.Interaction, prize: str, duration: int, name: str, role: discord.Role = None): view = GiveawayView(interaction.user, prize, name, role, discord.timedelta(seconds=duration)) embed = discord.Embed(title="🎉 Giveaway! 🎉", description=f"Prize: {prize}", color=discord.Color.gold()) embed.add_field(name="Donated By", value=name, inline=False) embed.add_field(name="Participants", value="0", inline=False) embed.set_footer(text=f"Ends in {duration // 60}m {duration % 60}s")

message = await interaction.response.send_message(embed=embed, view=view)
sent = await interaction.original_response()
view.message = sent
view.guild_id = interaction.guild_id
view.task = asyncio.create_task(view.update_embed())

@bot.event async def on_ready(): await tree.sync() print(f"Logged in as {bot.user}")

keep_alive() bot.run(os.getenv("TOKEN"))

