import os
import threading
import discord
from discord import app_commands
from flask import Flask, redirect, request, session
import requests
import urllib.parse
import sqlite3

# ==============================
# CONFIG
# ==============================

TOKEN = os.getenv("TOKEN")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")

# ==============================
# DATABASE
# ==============================

def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS server_settings (
            guild_id TEXT PRIMARY KEY,
            xp_enabled INTEGER DEFAULT 1,
            xp_multiplier INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ==============================
# DISCORD BOT
# ==============================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user}")

@tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    latency = round(client.latency * 1000)
    await interaction.response.send_message(f"Pong! {latency}ms")

# ==============================
# FLASK APP
# ==============================

app = Flask(__name__)
app.secret_key = CLIENT_SECRET

# ------------------------------
# LANDING PAGE
# ------------------------------
@app.route("/")
def home():
    return """
    <html>
    <body style="background:#0f1117;color:white;font-family:Arial;text-align:center;padding:100px;">
        <h1>Fun Fact Bot</h1>
        <p>Modern Discord XP & Economy Bot</p>
        <a href="/login" style="padding:12px 25px;background:#5865F2;color:white;text-decoration:none;border-radius:8px;">
        Login with Discord
        </a>
    </body>
    </html>
    """

# ------------------------------
# LOGIN
# ------------------------------
@app.route("/login")
def login():
    scope = "identify guilds"
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": scope
    }
    url = "https://discord.com/api/oauth2/authorize?" + urllib.parse.urlencode(params)
    return redirect(url)

# ------------------------------
# CALLBACK
# ------------------------------
@app.route("/callback")
def callback():
    code = request.args.get("code")

    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    r = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
    token_json = r.json()
    access_token = token_json.get("access_token")

    user = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"}
    ).json()

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["avatar"] = user["avatar"]
    session["access_token"] = access_token

    return redirect("/dashboard")

# ------------------------------
# DASHBOARD
# ------------------------------
@app.route("/dashboard")
def dashboard():
    if "access_token" not in session:
        return redirect("/login")

    access_token = session["access_token"]

    guilds = requests.get(
        "https://discord.com/api/users/@me/guilds",
        headers={"Authorization": f"Bearer {access_token}"}
    ).json()

    bot_guild_ids = [g.id for g in client.guilds]

    avatar_url = f"https://cdn.discordapp.com/avatars/{session['user_id']}/{session['avatar']}.png"

    guild_cards = ""

    for g in guilds:
        if int(g["permissions"]) & 0x20:

            if g["icon"]:
                icon_url = f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png"
            else:
                icon_url = "https://via.placeholder.com/64"

            if int(g["id"]) in bot_guild_ids:
                button = f'<a class="manage" href="/server/{g["id"]}">Manage</a>'
            else:
                button = f'<a class="add" href="https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&scope=bot&permissions=8">Add Bot</a>'

            guild_cards += f"""
            <div class="card">
                <img src="{icon_url}" class="icon">
                <h3>{g['name']}</h3>
                {button}
            </div>
            """

    return f"""
    <html>
    <head>
    <style>
    body {{margin:0;font-family:Arial;background:#0f1117;color:white;}}
    .navbar {{display:flex;justify-content:space-between;padding:20px 40px;background:#151822;}}
    .avatar {{width:40px;height:40px;border-radius:50%;}}
    .grid {{display:flex;flex-wrap:wrap;gap:25px;padding:40px;}}
    .card {{background:#151822;padding:25px;border-radius:15px;width:220px;text-align:center;}}
    .icon {{width:64px;height:64px;border-radius:50%;margin-bottom:15px;}}
    .manage {{background:#5865F2;padding:8px 16px;color:white;text-decoration:none;border-radius:8px;}}
    .add {{background:#43b581;padding:8px 16px;color:white;text-decoration:none;border-radius:8px;}}
    .logout {{color:red;text-decoration:none;}}
    </style>
    </head>
    <body>
    <div class="navbar">
        <h2>Fun Fact Bot</h2>
        <div>
            {session['username']}
            <img src="{avatar_url}" class="avatar">
            <a class="logout" href="/logout">Logout</a>
        </div>
    </div>
    <div class="grid">{guild_cards}</div>
    </body>
    </html>
    """

# ------------------------------
# SERVER PAGE
# ------------------------------
@app.route("/server/<int:guild_id>")
def server_page(guild_id):

    if "access_token" not in session:
        return redirect("/login")

    access_token = session["access_token"]

    guilds = requests.get(
        "https://discord.com/api/users/@me/guilds",
        headers={"Authorization": f"Bearer {access_token}"}
    ).json()

    allowed = False
    for g in guilds:
        if int(g["id"]) == guild_id and int(g["permissions"]) & 0x20:
            allowed = True
            break

    if not allowed:
        return "No permission."

    guild = client.get_guild(guild_id)
    if not guild:
        return "Bot not in this server."

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT xp_enabled, xp_multiplier FROM server_settings WHERE guild_id = ?", (str(guild_id),))
    row = c.fetchone()

    if not row:
        c.execute("INSERT INTO server_settings (guild_id) VALUES (?)", (str(guild_id),))
        conn.commit()
        xp_enabled, xp_multiplier = 1, 1
    else:
        xp_enabled, xp_multiplier = row

    conn.close()

    return f"""
    <html>
    <body style="background:#0f1117;color:white;font-family:Arial;padding:40px;">
        <h1>{guild.name}</h1>

        <form method="POST" action="/save/{guild_id}">
            <label>XP Enabled</label><br>
            <select name="xp_enabled">
                <option value="1" {"selected" if xp_enabled==1 else ""}>Enabled</option>
                <option value="0" {"selected" if xp_enabled==0 else ""}>Disabled</option>
            </select><br><br>

            <label>XP Multiplier</label><br>
            <input type="number" name="xp_multiplier" value="{xp_multiplier}" min="1" max="10"><br><br>

            <button type="submit">Save</button>
        </form>

        <br><a href="/dashboard">← Back</a>
    </body>
    </html>
    """

# ------------------------------
# SAVE SETTINGS
# ------------------------------
@app.route("/save/<int:guild_id>", methods=["POST"])
def save_settings(guild_id):

    if "access_token" not in session:
        return redirect("/login")

    xp_enabled = int(request.form.get("xp_enabled"))
    xp_multiplier = int(request.form.get("xp_multiplier"))

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
        INSERT INTO server_settings (guild_id, xp_enabled, xp_multiplier)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id)
        DO UPDATE SET
            xp_enabled = excluded.xp_enabled,
            xp_multiplier = excluded.xp_multiplier
    """, (str(guild_id), xp_enabled, xp_multiplier))

    conn.commit()
    conn.close()

    return redirect(f"/server/{guild_id}")

# ------------------------------
# LOGOUT
# ------------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ------------------------------
# START BOT THREAD
# ------------------------------
def run_bot():
    client.run(TOKEN)

threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
