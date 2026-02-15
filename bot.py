import discord
import requests
import asyncio
from datetime import datetime, time, timedelta

TOKEN = "MTQ3MjQ0NjA3MjgzOTIxMzIyOQ.GPiu-s.ktYiRCDk706G7oB_WwA1E-516ZMEroLzWLASis"
CHANNEL_ID = 1472458985083899975  # your channel id

SEND_HOUR = 12      # change this (24 hour format)
SEND_MINUTE = 0    # change this

intents = discord.Intents.default()
client = discord.Client(intents=intents)

def get_fun_fact():
    try:
        r = requests.get("https://uselessfacts.jsph.pl/random.json?language=en")
        return r.json()["text"]
    except:
        return "Fun fact machine broke today 🤖"

async def wait_until_target_time():
    now = datetime.now()
    target = datetime.combine(now.date(), time(SEND_HOUR, SEND_MINUTE))

    if now > target:
        target += timedelta(days=1)

    wait_seconds = (target - now).total_seconds()
    await asyncio.sleep(wait_seconds)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    channel = await client.fetch_channel(CHANNEL_ID)

    while True:
        await wait_until_target_time()
        await channel.send(f"🌟 Daily Fun Fact 🌟\n\n{get_fun_fact()}")
        await asyncio.sleep(60)

client.run(TOKEN)
