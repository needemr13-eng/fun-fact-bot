import discord
from discord import app_commands
import requests
import os
import sqlite3
import random
import html
from datetime import datetime, timedelta
from flask import Flask
import threading

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("TOKEN")

# =========================
# DISCORD SETUP
# =========================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# =========================
# DATABASE
# =========================

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS economy (
    guild_id INTEGER,
    user_id INTEGER,
    coins INTEGER DEFAULT 0,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
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

def create_bar(current, level):
    needed = xp_needed(level)
    ratio = min(current / needed, 1)
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

    leveled = False
    while xp >= xp_needed(level):
        xp -= xp_needed(level)
        level += 1
        leveled = True

    cursor.execute("""
    UPDATE economy SET xp=?, level=? WHERE guild_id=? AND user_id=?
    """, (xp, level, guild_id, user_id))
    conn.commit()

    return leveled, level, xp

def add_coins(guild_id, user_id, amount):
    cursor.execute("""
    INSERT INTO economy (guild_id, user_id, coins)
    VALUES (?, ?, ?)
    ON CONFLICT(guild_id, user_id)
    DO UPDATE SET coins = coins + ?
    """, (guild_id, user_id, amount, amount))
    conn.commit()

# =========================
# SLASH COMMANDS
# =========================

@tree.command(name="balance", description="Check your balance and XP")
async def balance(interaction: discord.Interaction):
    cursor.execute("""
    SELECT coins, xp, level FROM economy
    WHERE guild_id=? AND user_id=?
    """, (interaction.guild_id, interaction.user.id))
    data = cursor.fetchone()

    if not data:
        await interaction.response.send_message("You have no data yet.")
        return

    coins, xp, level = data
    bar = create_bar(xp, level)

    embed = discord.Embed(title="Your Stats", color=discord.Color.blurple())
    embed.add_field(name="Coins", value=str(coins))
    embed.add_field(name="Level", value=str(level))
    embed.add_field(name="XP Progress", value=bar, inline=False)

    await interaction.response.send_message(embed=embed)

@tree.command(name="daily", description="Claim daily coins")
async def daily(interaction: discord.Interaction):
    now = datetime.utcnow()

    cursor.execute("""
    SELECT last_daily FROM economy
    WHERE guild_id=? AND user_id=?
    """, (interaction.guild_id, interaction.user.id))
    row = cursor.fetchone()

    if row and row[0]:
        last = datetime.fromisoformat(row[0])
        if now - last < timedelta(hours=24):
            await interaction.response.send_message("Come back later ⏳")
            return

    add_coins(interaction.guild_id, interaction.user.id, 25)

    cursor.execute("""
    INSERT INTO economy (guild_id, user_id, last_daily)
    VALUES (?, ?, ?)
    ON CONFLICT(guild_id, user_id)
    DO UPDATE SET last_daily=?
    """, (interaction.guild_id, interaction.user.id,
          now.isoformat(), now.isoformat()))
    conn.commit()

    await interaction.response.send_message("You received 25 coins! 💰")

@tree.command(name="leaderboard", description="Server leaderboard")
async def leaderboard(interaction: discord.Interaction):
    cursor.execute("""
    SELECT user_id, level FROM economy
    WHERE guild_id=?
    ORDER BY level DESC LIMIT 10
    """, (interaction.guild_id,))
    rows = cursor.fetchall()

    if not rows:
        await interaction.response.send_message("No data yet.")
        return

    text = ""
    for i, (uid, level) in enumerate(rows, 1):
        user = await client.fetch_user(uid)
        text += f"{i}. {user.name} — Level {level}\n"

    await interaction.response.send_message(f"🏆 Server Leaderboard\n\n{text}")

@tree.command(name="trivia", description="Answer a trivia question")
async def trivia(interaction: discord.Interaction):
    r = requests.get("https://opentdb.com/api.php?amount=1&type=multiple")
    data = r.json()["results"][0]

    question = html.unescape(data["question"])
    correct = html.unescape(data["correct_answer"])
    options = [html.unescape(i) for i in data["incorrect_answers"]] + [correct]
    random.shuffle(options)

    view = discord.ui.View(timeout=30)

    for option in options:
        async def callback(inter2: discord.Interaction, opt=option):
            if opt == correct:
                add_coins(interaction.guild_id, inter2.user.id, 10)
                add_xp(interaction.guild_id, inter2.user.id, 20)
                await inter2.response.send_message(
                    "Correct! +10 coins +20 XP 🎉", ephemeral=True)
            else:
                await inter2.response.send_message(
                    f"Wrong! Answer: {correct}", ephemeral=True)

        btn = discord.ui.Button(label=option)
        btn.callback = callback
        view.add_item(btn)

    await interaction.response.send_message(question, view=view)

# =========================
# READY EVENT
# =========================

@client.event
async def on_ready():
    await tree.sync()
    print(f"Bot ready as {client.user}")

# =========================
# FLASK DASHBOARD
# =========================

app = Flask(__name__)

@app.route("/")
def dashboard():
    if not client.is_ready():
        return "<h1>Bot is starting...</h1>"

    servers = len(client.guilds)
    users = sum(g.member_count for g in client.guilds if g.member_count)
    latency = round(client.latency * 1000)

    return f"""
    <h1>Fun Fact Bot Dashboard</h1>
    <p>Servers: {servers}</p>
    <p>Users: {users}</p>
    <p>Ping: {latency} ms</p>
    <a href="/leaderboard">View Global Leaderboard</a>
    """

@app.route("/leaderboard")
def web_leaderboard():
    cursor.execute("""
    SELECT user_id, level FROM economy
    ORDER BY level DESC LIMIT 10
    """)
    rows = cursor.fetchall()

    text = ""
    for i, (uid, level) in enumerate(rows, 1):
        text += f"<p>#{i} — User ID {uid} — Level {level}</p>"

    return f"""
    <h1>Global Leaderboard</h1>
    {text}
    <br>
    <a href="/">Back</a>
    """

# =========================
# START DISCORD (Gunicorn Safe)
# =========================

def start_bot():
    if not TOKEN:
        print("TOKEN missing!")
        return
    print("Starting Discord bot...")
    client.run(TOKEN)

threading.Thread(target=start_bot, daemon=True).start()
