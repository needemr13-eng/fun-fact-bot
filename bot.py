import discord
from discord import app_commands
from discord.ext import tasks
import requests
import asyncio
import os
import sqlite3
import random
import html
from datetime import datetime

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# =========================
# DATABASE SETUP
# =========================

conn = sqlite3.connect("database.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    hour INTEGER DEFAULT 7,
    minute INTEGER DEFAULT 30,
    enabled INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS leaderboard (
    guild_id INTEGER,
    user_id INTEGER,
    points INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
""")

conn.commit()

# =========================
# UTIL FUNCTIONS
# =========================

def get_fun_fact():
    try:
        r = requests.get("https://uselessfacts.jsph.pl/random.json?language=en")
        return r.json()["text"]
    except:
        return "Fun fact machine broke 🤖"

def get_trivia_question():
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

def add_points(guild_id, user_id):
    cursor.execute("""
    INSERT INTO leaderboard (guild_id, user_id, points)
    VALUES (?, ?, 1)
    ON CONFLICT(guild_id, user_id)
    DO UPDATE SET points = points + 1
    """, (guild_id, user_id))
    conn.commit()

# =========================
# DAILY FACT LOOP
# =========================

@tasks.loop(minutes=1)
async def daily_fact_loop():
    now = datetime.utcnow()

    cursor.execute("SELECT guild_id, channel_id, hour, minute FROM guild_settings WHERE enabled = 1")
    rows = cursor.fetchall()

    for guild_id, channel_id, hour, minute in rows:
        if now.hour == hour and now.minute == minute:
            channel = client.get_channel(channel_id)
            if channel:
                await channel.send(f"🌟 **Daily Fun Fact** 🌟\n\n{get_fun_fact()}")

# =========================
# EVENTS
# =========================

@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user}")
    daily_fact_loop.start()

# =========================
# FUN COMMANDS
# =========================

@tree.command(name="fact", description="Get a random fun fact!")
async def fact(interaction: discord.Interaction):
    await interaction.response.send_message(f"🌟 {get_fun_fact()}")

@tree.command(name="trivia", description="Start a trivia question!")
async def trivia(interaction: discord.Interaction):
    question, correct, options = get_trivia_question()

    if not question:
        await interaction.response.send_message("Trivia API failed 😭")
        return

    view = discord.ui.View(timeout=30)

    for option in options:
        async def button_callback(interaction2: discord.Interaction, opt=option):
            if opt == correct:
                add_points(interaction.guild_id, interaction2.user.id)
                await interaction2.response.send_message("✅ Correct! +1 point", ephemeral=True)
            else:
                await interaction2.response.send_message(f"❌ Wrong! Correct answer: {correct}", ephemeral=True)

        button = discord.ui.Button(label=option, style=discord.ButtonStyle.primary)
        button.callback = button_callback
        view.add_item(button)

    await interaction.response.send_message(f"🧠 **Trivia Time!**\n\n{question}", view=view)

@tree.command(name="leaderboard", description="View trivia leaderboard.")
async def leaderboard(interaction: discord.Interaction):
    cursor.execute("""
    SELECT user_id, points FROM leaderboard
    WHERE guild_id = ?
    ORDER BY points DESC LIMIT 10
    """, (interaction.guild_id,))
    rows = cursor.fetchall()

    if not rows:
        await interaction.response.send_message("No scores yet!")
        return

    text = ""
    for i, (user_id, points) in enumerate(rows, start=1):
        text += f"{i}. <@{user_id}> - {points} pts\n"

    await interaction.response.send_message(f"🏆 **Leaderboard** 🏆\n\n{text}")

# =========================
# ADMIN COMMANDS
# =========================

@tree.command(name="setchannel", description="Set daily fact channel.")
@app_commands.checks.has_permissions(administrator=True)
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    cursor.execute("""
    INSERT INTO guild_settings (guild_id, channel_id)
    VALUES (?, ?)
    ON CONFLICT(guild_id)
    DO UPDATE SET channel_id = ?
    """, (interaction.guild_id, channel.id, channel.id))
    conn.commit()
    await interaction.response.send_message(f"Daily facts will post in {channel.mention}")

@tree.command(name="settime", description="Set daily fact time (UTC).")
@app_commands.checks.has_permissions(administrator=True)
async def settime(interaction: discord.Interaction, hour: int, minute: int):
    cursor.execute("""
    INSERT INTO guild_settings (guild_id, hour, minute)
    VALUES (?, ?, ?)
    ON CONFLICT(guild_id)
    DO UPDATE SET hour = ?, minute = ?
    """, (interaction.guild_id, hour, minute, hour, minute))
    conn.commit()
    await interaction.response.send_message(f"Daily fact time set to {hour:02d}:{minute:02d} UTC")

@tree.command(name="enablefacts", description="Enable daily facts.")
@app_commands.checks.has_permissions(administrator=True)
async def enablefacts(interaction: discord.Interaction):
    cursor.execute("""
    INSERT INTO guild_settings (guild_id, enabled)
    VALUES (?, 1)
    ON CONFLICT(guild_id)
    DO UPDATE SET enabled = 1
    """, (interaction.guild_id,))
    conn.commit()
    await interaction.response.send_message("✅ Daily facts enabled.")

@tree.command(name="disablefacts", description="Disable daily facts.")
@app_commands.checks.has_permissions(administrator=True)
async def disablefacts(interaction: discord.Interaction):
    cursor.execute("UPDATE guild_settings SET enabled = 0 WHERE guild_id = ?", (interaction.guild_id,))
    conn.commit()
    await interaction.response.send_message("❌ Daily facts disabled.")

@tree.command(name="resetleaderboard", description="Reset trivia leaderboard.")
@app_commands.checks.has_permissions(administrator=True)
async def resetleaderboard(interaction: discord.Interaction):
    cursor.execute("DELETE FROM leaderboard WHERE guild_id = ?", (interaction.guild_id,))
    conn.commit()
    await interaction.response.send_message("Leaderboard reset.")

# =========================
# UTILITY COMMANDS
# =========================

@tree.command(name="ping", description="Check bot latency.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! {round(client.latency * 1000)}ms")

@tree.command(name="serverinfo", description="Get server info.")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    await interaction.response.send_message(
        f"**{guild.name}**\nMembers: {guild.member_count}\nCreated: {guild.created_at.date()}"
    )

@tree.command(name="userinfo", description="Get user info.")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    await interaction.response.send_message(
        f"**{member.name}**\nJoined: {member.joined_at.date()}"
    )

@tree.command(name="stats", description="Bot stats.")
async def stats(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Servers: {len(client.guilds)}\nUsers: {len(client.users)}"
    )

client.run(TOKEN)
