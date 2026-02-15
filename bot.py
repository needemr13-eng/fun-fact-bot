import discord
from discord import app_commands
import requests
import asyncio
import os
import json
from datetime import datetime, time, timedelta

TOKEN = os.getenv("TOKEN")

# 🔥 PUT YOUR REAL SERVER ID HERE
GUILD_ID = 1472394773959671912

CONFIG_FILE = "config.json"

# Default settings
config = {
    "channel_id": 1472458985083899975,  # default channel
    "hour": 7,
    "minute": 30
}

# Load saved settings
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

guild = discord.Object(id=GUILD_ID)

def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

def get_fun_fact():
    try:
        r = requests.get("https://uselessfacts.jsph.pl/random.json?language=en")
        return r.json()["text"]
    except:
        return "Fun fact machine broke today 🤖"

# ---------- EMBED ----------
def create_fact_embed():
    embed = discord.Embed(
        title="🌟 Fun Fact",
        description=get_fun_fact(),
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Powered by your awesome bot 😎")
    return embed

# ---------- BUTTON ----------
class FactView(discord.ui.View):
    @discord.ui.button(label="Another Fact", style=discord.ButtonStyle.primary)
    async def another_fact(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=create_fact_embed(), view=self)

# ---------- SLASH COMMANDS (GUILD SYNCED) ----------

@tree.command(name="fact", description="Get a random fun fact!", guild=guild)
async def fact(interaction: discord.Interaction):
    await interaction.response.send_message(embed=create_fact_embed(), view=FactView())


@tree.command(name="settime", description="Set daily fact time (24h format)", guild=guild)
@app_commands.describe(hour="Hour (0-23)", minute="Minute (0-59)")
async def settime(interaction: discord.Interaction, hour: int, minute: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return

    config["hour"] = hour
    config["minute"] = minute
    save_config()

    await interaction.response.send_message(f"✅ Daily time set to {hour:02d}:{minute:02d}")


@tree.command(name="setchannel", description="Set channel for daily facts", guild=guild)
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return

    config["channel_id"] = channel.id
    save_config()

    await interaction.response.send_message(f"✅ Daily facts will now send in {channel.mention}")

# ---------- DAILY LOOP ----------

async def wait_until_target_time():
    now = datetime.now()
    target = datetime.combine(now.date(), time(config["hour"], config["minute"]))

    if now > target:
        target += timedelta(days=1)

    await asyncio.sleep((target - now).total_seconds())

@client.event
async def on_ready():
    synced = await tree.sync(guild=guild)
    print(f"Logged in as {client.user}")
    print(f"Synced {len(synced)} commands.")

    while True:
        await wait_until_target_time()
        channel = await client.fetch_channel(config["channel_id"])
        await channel.send(embed=create_fact_embed(), view=FactView())
        await asyncio.sleep(60)

client.run(TOKEN)
