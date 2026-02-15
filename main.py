import discord
from discord import app_commands
from discord.ext import tasks
import requests
import os
import sqlite3
import random
import html
from datetime import datetime, timedelta
import math

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# =========================
# DATABASE
# =========================

conn = sqlite3.connect("database.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    hour INTEGER DEFAULT 7,
    minute INTEGER DEFAULT 30,
    enabled INTEGER DEFAULT 0,
    level_channel_id INTEGER,
    levels_enabled INTEGER DEFAULT 1
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS economy (
    guild_id INTEGER,
    user_id INTEGER,
    coins INTEGER DEFAULT 0,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    streak INTEGER DEFAULT 0,
    last_daily TEXT,
    PRIMARY KEY (guild_id, user_id)
)
""")

conn.commit()

# =========================
# XP SYSTEM
# =========================

def xp_needed(level):
    return int(100 * (level ** 1.5))

def create_xp_bar(current_xp, level):
    needed = xp_needed(level)
    ratio = min(current_xp / needed, 1)
    filled = int(ratio * 10)
    return "▰" * filled + "▱" * (10 - filled)

def add_xp(guild_id, user_id, amount):
    cursor.execute("""
    INSERT INTO economy (guild_id, user_id, xp)
    VALUES (?, ?, ?)
    ON CONFLICT(guild_id, user_id)
    DO UPDATE SET xp = xp + ?
    """, (guild_id, user_id, amount, amount))
    conn.commit()

    cursor.execute("SELECT xp, level FROM economy WHERE guild_id=? AND user_id=?",
                   (guild_id, user_id))
    xp, level = cursor.fetchone()

    leveled_up = False

    while xp >= xp_needed(level):
        xp -= xp_needed(level)
        level += 1
        leveled_up = True

    cursor.execute("""
    UPDATE economy SET xp=?, level=? WHERE guild_id=? AND user_id=?
    """, (xp, level, guild_id, user_id))
    conn.commit()

    return leveled_up, level, xp

def add_coins(guild_id, user_id, amount):
    cursor.execute("""
    INSERT INTO economy (guild_id, user_id, coins)
    VALUES (?, ?, ?)
    ON CONFLICT(guild_id, user_id)
    DO UPDATE SET coins = coins + ?
    """, (guild_id, user_id, amount, amount))
    conn.commit()

# =========================
# TRIVIA
# =========================

def get_trivia():
    try:
        r = requests.get("https://opentdb.com/api.php?amount=1&type=multiple")
        data = r.json()["results"][0]
        question = html.unescape(data["question"])
        correct = html.unescape(data["correct_answer"])
        incorrect = [html.unescape(i) for i in data["incorrect_answers"]]
        options = incorrect + [correct]
        random.shuffle(options)
        return question, correct, options
    except:
        return None, None, None

@tree.command(name="trivia", description="Start a trivia question!")
async def trivia(interaction: discord.Interaction):
    question, correct, options = get_trivia()

    if not question:
        await interaction.response.send_message("Trivia failed 😭")
        return

    view = discord.ui.View(timeout=30)

    for option in options:
        async def callback(interaction2: discord.Interaction, opt=option):
            if opt == correct:
                add_coins(interaction.guild_id, interaction2.user.id, 1)
                leveled, level, xp = add_xp(interaction.guild_id, interaction2.user.id, 15)

                await interaction2.response.send_message("✅ Correct! +1 coin +15 XP", ephemeral=True)

                if leveled:
                    await send_level_up(interaction.guild_id, interaction2.user, level, xp)
            else:
                await interaction2.response.send_message(
                    f"❌ Wrong! Correct: {correct}", ephemeral=True)

        button = discord.ui.Button(label=option, style=discord.ButtonStyle.primary)
        button.callback = callback
        view.add_item(button)

    await interaction.response.send_message(f"🧠 **Trivia Time!**\n\n{question}", view=view)

# =========================
# LEVEL UP EMBED
# =========================

async def send_level_up(guild_id, user, level, xp):
    cursor.execute("""
    SELECT level_channel_id, levels_enabled FROM guild_settings WHERE guild_id=?
    """, (guild_id,))
    result = cursor.fetchone()

    if not result:
        return

    channel_id, enabled = result
    if not enabled or not channel_id:
        return

    channel = client.get_channel(channel_id)
    if not channel:
        return

    bar = create_xp_bar(xp, level)

    embed = discord.Embed(
        title="🎉 Level Up!",
        description=f"{user.mention} reached **Level {level}**!",
        color=discord.Color.gold()
    )
    embed.add_field(name="XP Progress", value=f"{bar}", inline=False)
    embed.set_thumbnail(url=user.display_avatar.url)

    await channel.send(embed=embed)

# =========================
# ECONOMY COMMANDS
# =========================

@tree.command(name="balance", description="Check your balance and level.")
async def balance(interaction: discord.Interaction):
    cursor.execute("""
    SELECT coins, xp, level FROM economy WHERE guild_id=? AND user_id=?
    """, (interaction.guild_id, interaction.user.id))
    data = cursor.fetchone()

    if not data:
        await interaction.response.send_message("You have nothing yet 😭")
        return

    coins, xp, level = data
    bar = create_xp_bar(xp, level)

    embed = discord.Embed(title="💰 Your Stats", color=discord.Color.blue())
    embed.add_field(name="Coins", value=str(coins))
    embed.add_field(name="Level", value=str(level))
    embed.add_field(name="XP", value=bar, inline=False)

    await interaction.response.send_message(embed=embed)

@tree.command(name="daily", description="Claim daily reward.")
async def daily(interaction: discord.Interaction):
    cursor.execute("""
    SELECT last_daily FROM economy WHERE guild_id=? AND user_id=?
    """, (interaction.guild_id, interaction.user.id))
    row = cursor.fetchone()

    now = datetime.utcnow()

    if row and row[0]:
        last = datetime.fromisoformat(row[0])
        if now - last < timedelta(hours=24):
            await interaction.response.send_message("Come back later ⏳")
            return

    add_coins(interaction.guild_id, interaction.user.id, 10)

    cursor.execute("""
    INSERT INTO economy (guild_id, user_id, last_daily)
    VALUES (?, ?, ?)
    ON CONFLICT(guild_id, user_id)
    DO UPDATE SET last_daily=?
    """, (interaction.guild_id, interaction.user.id, now.isoformat(), now.isoformat()))
    conn.commit()

    await interaction.response.send_message("💰 You received 10 coins!")

# =========================
# ADMIN LEVEL SETTINGS
# =========================

@tree.command(name="setlevelchannel", description="Set level-up channel.")
@app_commands.checks.has_permissions(administrator=True)
async def setlevelchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    cursor.execute("""
    INSERT INTO guild_settings (guild_id, level_channel_id)
    VALUES (?, ?)
    ON CONFLICT(guild_id)
    DO UPDATE SET level_channel_id=?
    """, (interaction.guild_id, channel.id, channel.id))
    conn.commit()
    await interaction.response.send_message(f"Level-ups will post in {channel.mention}")

@tree.command(name="togglelevels", description="Enable/Disable level messages.")
@app_commands.checks.has_permissions(administrator=True)
async def togglelevels(interaction: discord.Interaction):
    cursor.execute("SELECT levels_enabled FROM guild_settings WHERE guild_id=?",
                   (interaction.guild_id,))
    row = cursor.fetchone()

    new_value = 0 if row and row[0] == 1 else 1

    cursor.execute("""
    INSERT INTO guild_settings (guild_id, levels_enabled)
    VALUES (?, ?)
    ON CONFLICT(guild_id)
    DO UPDATE SET levels_enabled=?
    """, (interaction.guild_id, new_value, new_value))
    conn.commit()

    status = "enabled" if new_value else "disabled"
    await interaction.response.send_message(f"Level messages {status}.")

@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user}")

import threading
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "<h1>Bot Dashboard Running 🚀</h1>"

def run_bot():
    client.run(TOKEN)

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    run_web()


