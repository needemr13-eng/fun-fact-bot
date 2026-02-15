import discord
from discord import app_commands
import requests
import asyncio
import os
from datetime import datetime, time, timedelta

TOKEN = os.getenv("TOKEN")
print("TOKEN VALUE:", TOKEN)
CHANNEL_ID = 1472458985083899975  # your channel id

SEND_HOUR = 7
SEND_MINUTE = 30

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

def get_fun_fact():
    try:
        r = requests.get("https://uselessfacts.jsph.pl/random.json?language=en")
        return r.json()["text"]
    except:
        return "Fun fact machine broke today 🤖"

# ✅ Slash Command
@tree.command(name="fact", description="Get a random fun fact!")
async def fact(interaction: discord.Interaction):
    await interaction.response.send_message(f"🌟 {get_fun_fact()}")

async def wait_until_target_time():
    now = datetime.now()
    target = datetime.combine(now.date(), time(SEND_HOUR, SEND_MINUTE))

    if now > target:
        target += timedelta(days=1)

    wait_seconds = (target - now).total_seconds()
    await asyncio.sleep(wait_seconds)

@client.event
async def on_ready():
    await tree.sync()  # sync slash commands
    print(f"Logged in as {client.user}")

    channel = await client.fetch_channel(CHANNEL_ID)

    while True:
        await wait_until_target_time()
        await channel.send(f"🌟 Daily Fun Fact 🌟\n\n{get_fun_fact()}")
        await asyncio.sleep(60)

client.run(TOKEN)



