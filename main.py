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
        return "<h1 style='color:white;background:#0f1117;padding:50px;'>Bot is starting...</h1>"

    servers = len(client.guilds)
    users = sum(g.member_count for g in client.guilds if g.member_count)
    latency = round(client.latency * 1000)

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Fun Fact Bot Dashboard</title>
        <meta http-equiv="refresh" content="15">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            body {{
                margin: 0;
                font-family: 'Inter', sans-serif;
                background: #0f1117;
                color: white;
                display: flex;
            }}

            .sidebar {{
                width: 250px;
                background: #151822;
                height: 100vh;
                padding: 30px;
                box-shadow: 5px 0 20px rgba(0,0,0,0.4);
            }}

            .logo {{
                font-size: 22px;
                font-weight: 700;
                background: linear-gradient(90deg, #5865F2, #9b59ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 40px;
            }}

            .sidebar a {{
                display: block;
                text-decoration: none;
                color: #aaa;
                padding: 12px;
                border-radius: 10px;
                margin-bottom: 10px;
                transition: 0.2s;
            }}

            .sidebar a:hover {{
                background: #1f2330;
                color: white;
            }}

            .main {{
                flex: 1;
                padding: 40px;
            }}

            .topbar {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 40px;
            }}

            .topbar h1 {{
                font-size: 28px;
                margin: 0;
            }}

            .status {{
                padding: 8px 15px;
                background: #1f2330;
                border-radius: 20px;
                font-size: 14px;
                color: #4CAF50;
            }}

            .cards {{
                display: flex;
                gap: 30px;
                flex-wrap: wrap;
            }}

            .card {{
                background: #151822;
                padding: 30px;
                border-radius: 18px;
                width: 260px;
                box-shadow: 0 0 25px rgba(0,0,0,0.5);
                transition: 0.25s ease;
                position: relative;
                overflow: hidden;
            }}

            .card::before {{
                content: "";
                position: absolute;
                top: -50%;
                left: -50%;
                width: 200%;
                height: 200%;
                background: radial-gradient(circle, rgba(88,101,242,0.15) 0%, transparent 60%);
                transform: rotate(25deg);
            }}

            .card:hover {{
                transform: translateY(-8px);
                box-shadow: 0 0 35px rgba(88,101,242,0.3);
            }}

            .card h3 {{
                margin: 0;
                font-size: 15px;
                color: #888;
                letter-spacing: 1px;
                text-transform: uppercase;
            }}

            .card p {{
                font-size: 38px;
                margin-top: 15px;
                font-weight: 700;
                background: linear-gradient(90deg, #5865F2, #9b59ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }}

            .footer {{
                margin-top: 60px;
                font-size: 13px;
                color: #555;
            }}
        </style>
    </head>

    <body>

        <div class="sidebar">
            <div class="logo">Fun Fact Bot</div>
            <a href="/">🏠 Dashboard</a>
            <a href="/leaderboard">🏆 Leaderboard</a>
        </div>

        <div class="main">
            <div class="topbar">
                <h1>Dashboard Overview</h1>
                <div class="status">● Online</div>
            </div>

            <div class="cards">
                <div class="card">
                    <h3>Servers</h3>
                    <p>{servers}</p>
                </div>

                <div class="card">
                    <h3>Total Users</h3>
                    <p>{users}</p>
                </div>

                <div class="card">
                    <h3>Latency</h3>
                    <p>{latency}ms</p>
                </div>
            </div>

            <div class="footer">
                Fun Fact Bot © 2026 — Powered by Flask + Discord.py
            </div>
        </div>

    </body>
    </html>
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


