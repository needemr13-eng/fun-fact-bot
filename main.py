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
    return """
<!DOCTYPE html>
<html>
<head>
<title>Fun Fact Bot Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
body {
    margin: 0;
    font-family: 'Inter', sans-serif;
    background: linear-gradient(135deg, #0f1117, #131722);
    color: white;
    display: flex;
}

/* SIDEBAR */
.sidebar {
    width: 240px;
    background: rgba(20, 22, 32, 0.8);
    backdrop-filter: blur(15px);
    padding: 30px;
    height: 100vh;
    border-right: 1px solid rgba(255,255,255,0.05);
}

.logo {
    font-size: 22px;
    font-weight: 700;
    background: linear-gradient(90deg,#5865F2,#9b59ff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 40px;
}

.sidebar a {
    display: block;
    text-decoration: none;
    color: #aaa;
    padding: 12px;
    border-radius: 10px;
    margin-bottom: 10px;
    transition: 0.2s;
}

.sidebar a:hover {
    background: rgba(88,101,242,0.15);
    color: white;
}

/* MAIN */
.main {
    flex: 1;
    padding: 50px;
}

.topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 50px;
}

.status {
    padding: 8px 18px;
    border-radius: 20px;
    background: rgba(0,255,100,0.1);
    color: #4CAF50;
    font-weight: 600;
}

/* CARDS */
.cards {
    display: flex;
    gap: 30px;
    flex-wrap: wrap;
}

.card {
    background: rgba(25,28,40,0.6);
    backdrop-filter: blur(20px);
    padding: 35px;
    border-radius: 20px;
    width: 260px;
    position: relative;
    overflow: hidden;
    transition: 0.3s;
    border: 1px solid rgba(255,255,255,0.05);
}

.card:hover {
    transform: translateY(-8px);
    box-shadow: 0 0 40px rgba(88,101,242,0.3);
}

.card h3 {
    margin: 0;
    font-size: 14px;
    color: #888;
    text-transform: uppercase;
    letter-spacing: 1px;
}

.card p {
    font-size: 40px;
    margin-top: 15px;
    font-weight: 700;
    background: linear-gradient(90deg,#5865F2,#9b59ff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.footer {
    margin-top: 60px;
    font-size: 13px;
    color: #555;
}
</style>
</head>

<body>

<div class="sidebar">
    <div class="logo">Fun Fact Bot</div>
    <a href="/">🏠 Dashboard</a>
  <a href="/servers">🖥 Servers</a>
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
            <p id="servers">0</p>
        </div>

        <div class="card">
            <h3>Total Users</h3>
            <p id="users">0</p>
        </div>

        <div class="card">
            <h3>Latency</h3>
            <p id="latency">0ms</p>
        </div>
    </div>

    <div class="footer">
        Fun Fact Bot © 2026 — SaaS Mode Activated
    </div>
</div>

<script>
async function updateStats() {
    const res = await fetch("/stats");
    const data = await res.json();

    document.getElementById("servers").innerText = data.servers;
    document.getElementById("users").innerText = data.users;
    document.getElementById("latency").innerText = data.latency + "ms";
}

updateStats();
setInterval(updateStats, 5000);
</script>

</body>
</html>
"""

@app.route("/stats")
def stats():
    if not client.is_ready():
        return {"servers": 0, "users": 0, "latency": 0}

    return {
        "servers": len(client.guilds),
        "users": sum(g.member_count for g in client.guilds if g.member_count),
        "latency": round(client.latency * 1000)
    }




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


@app.route("/servers")
def servers():
    if not client.is_ready():
        return "Bot is starting..."

    server_cards = ""

    for guild in client.guilds:
        server_cards += f"""
        <div class="card">
            <h3>{guild.name}</h3>
            <p>{guild.member_count} Members</p>
            <a class="btn" href="/server/{guild.id}">Manage</a>
        </div>
        """

    return f"""
    <html>
    <head>
    <title>Servers</title>
    <style>
    body {{
        background:#0f1117;
        color:white;
        font-family:Inter,sans-serif;
        padding:50px;
    }}
    .grid {{
        display:flex;
        gap:25px;
        flex-wrap:wrap;
    }}
    .card {{
        background:#151822;
        padding:25px;
        border-radius:15px;
        width:250px;
    }}
    .btn {{
        display:inline-block;
        margin-top:10px;
        padding:8px 15px;
        background:#5865F2;
        color:white;
        text-decoration:none;
        border-radius:8px;
    }}
    </style>
    </head>
    <body>
        <h1>Your Servers</h1>
        <div class="grid">
            {server_cards}
        </div>
    </body>
    </html>
    """


@app.route("/server/<int:guild_id>")
def server_dashboard(guild_id):
    guild = client.get_guild(guild_id)

    if not guild:
        return "Server not found"

    members = guild.member_count
    channels = len(guild.channels)
    roles = len(guild.roles)

    return f"""
    <html>
    <head>
    <title>{guild.name}</title>
    <style>
    body {{
        background:#0f1117;
        color:white;
        font-family:Inter,sans-serif;
        padding:50px;
    }}
    .card {{
        background:#151822;
        padding:30px;
        border-radius:18px;
        width:300px;
        margin-bottom:20px;
    }}
    </style>
    </head>
    <body>
        <h1>{guild.name}</h1>

        <div class="card">
            <h3>Members</h3>
            <p>{members}</p>
        </div>

        <div class="card">
            <h3>Channels</h3>
            <p>{channels}</p>
        </div>

        <div class="card">
            <h3>Roles</h3>
            <p>{roles}</p>
        </div>

        <br>
        <a href="/servers" style="color:#5865F2;">← Back to servers</a>
    </body>
    </html>
    """


