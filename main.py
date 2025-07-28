import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
import asyncio
import os
import json
from datetime import datetime, timedelta
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

giveaways = {}

class JoinButton(Button):
    def __init__(self, giveaway_id):
        super().__init__(label="🎉 Join", style=discord.ButtonStyle.green)
        self.giveaway_id = giveaway_id

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        if user_id in giveaways[self.giveaway_id]["participants"]:
            await interaction.response.send_message("❌ You already joined!", ephemeral=True)
        else:
            giveaways[self.giveaway_id]["participants"].append(user_id)
            await interaction.response.send_message("✅ You joined the giveaway!", ephemeral=True)

class GiveawayView(View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.add_item(JoinButton(giveaway_id))

@tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(
    prize="What is the prize?",
    duration="Duration in seconds",
    winners="How many winners?"
)
async def giveaway(interaction: discord.Interaction, prize: str, duration: int, winners: int = 1):
    end_time = datetime.utcnow() + timedelta(seconds=duration)
    giveaway_id = str(interaction.id)

    giveaways[giveaway_id] = {
        "prize": prize,
        "end_time": end_time.isoformat(),
        "participants": [],
        "winners": winners,
        "message_id": None,
        "channel_id": interaction.channel.id
    }

    embed = discord.Embed(
        title="🎉 Giveaway Started!",
        description=f"**Prize:** {prize}\n**Ends in:** {duration} seconds\n**Hosted by:** {interaction.user.mention}\n\nClick the button below to join!",
        color=discord.Color.gold()
    )

    view = GiveawayView(giveaway_id)
    message = await interaction.channel.send(embed=embed, view=view)

    giveaways[giveaway_id]["message_id"] = message.id
    await interaction.response.send_message("✅ Giveaway started!", ephemeral=True)

    # Start countdown task
    async def countdown():
        while True:
            remaining = (end_time - datetime.utcnow()).total_seconds()
            if remaining <= 0:
                break

            try:
                embed.description = f"**Prize:** {prize}\n**Ends in:** {int(remaining)} seconds\n**Hosted by:** {interaction.user.mention}\n\n🎯 Participants: {len(giveaways[giveaway_id]['participants'])}"
                await message.edit(embed=embed, view=view)
            except discord.NotFound:
                break  # Message was deleted

            await asyncio.sleep(1)

        # Select winners
        participants = giveaways[giveaway_id]["participants"]
        if not participants:
            result = "😢 No one joined the giveaway."
        else:
            winners_list = [f"<@{uid}>" for uid in random.sample(participants, min(winners, len(participants)))]
            result = f"🎊 Congratulations {', '.join(winners_list)}! You won **{prize}**!"

        try:
            await message.reply(result)
        except:
            pass

    bot.loop.create_task(countdown())

@bot.event
async def on_ready():
    await tree.sync()
    print(f"Bot is ready: {bot.user}")

keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
