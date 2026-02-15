import os
import threading
import discord
from discord import app_commands
from flask import Flask, redirect, request, session
import requests
import urllib.parse

# ==============================
# CONFIG
# ==============================

TOKEN = os.getenv("TOKEN")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")

# ==============================
# DISCORD BOT SETUP
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

# Example Slash Command
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
# Landing Page
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

    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    r = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
    token_json = r.json()

    access_token = token_json.get("access_token")

    user = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"}
    ).json()

    # ✅ STORE ONLY SMALL DATA
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["access_token"] = access_token

    return redirect("/dashboard")


# ------------------------------
# DASHBOARD (Protected)
# ------------------------------
@app.route("/dashboard")
def dashboard():
    if "access_token" not in session:
        return redirect("/login")

    access_token = session["access_token"]

    # Fetch user info
    user = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"}
    ).json()

    avatar_url = f"https://cdn.discordapp.com/avatars/{user['id']}/{user['avatar']}.png"

    # Fetch user guilds
    guilds = requests.get(
        "https://discord.com/api/users/@me/guilds",
        headers={"Authorization": f"Bearer {access_token}"}
    ).json()

    bot_guild_ids = [g.id for g in client.guilds]

    guild_cards = ""

    for g in guilds:
        if int(g["permissions"]) & 0x20:

            icon_url = ""
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
    <title>Dashboard</title>
    <style>
    body {{
        margin:0;
        font-family:Inter, Arial;
        background:#0f1117;
        color:white;
    }}

    .navbar {{
        display:flex;
        justify-content:space-between;
        align-items:center;
        padding:20px 40px;
        background:#151822;
    }}

    .user {{
        display:flex;
        align-items:center;
        gap:15px;
    }}

    .avatar {{
        width:40px;
        height:40px;
        border-radius:50%;
    }}

    .grid {{
        display:flex;
        flex-wrap:wrap;
        gap:25px;
        padding:40px;
    }}

    .card {{
        background:#151822;
        padding:25px;
        border-radius:15px;
        width:220px;
        text-align:center;
        transition:0.3s;
    }}

    .card:hover {{
        transform:translateY(-5px);
        box-shadow:0 0 25px rgba(88,101,242,0.3);
    }}

    .icon {{
        width:64px;
        height:64px;
        border-radius:50%;
        margin-bottom:15px;
    }}

    .manage {{
        display:inline-block;
        margin-top:10px;
        padding:8px 16px;
        background:#5865F2;
        color:white;
        text-decoration:none;
        border-radius:8px;
    }}

    .add {{
        display:inline-block;
        margin-top:10px;
        padding:8px 16px;
        background:#43b581;
        color:white;
        text-decoration:none;
        border-radius:8px;
    }}

    .logout {{
        color:#ff5555;
        text-decoration:none;
    }}
    </style>
    </head>

    <body>

    <div class="navbar">
        <h2>Fun Fact Bot</h2>
        <div class="user">
            <span>{user['username']}</span>
            <img src="{avatar_url}" class="avatar">
            <a class="logout" href="/logout">Logout</a>
        </div>
    </div>

    <div class="grid">
        {guild_cards}
    </div>

    </body>
    </html>
    """



# ------------------------------
# PER SERVER PAGE
# ------------------------------
@app.route("/server/<int:guild_id>")
def server_page(guild_id):

    # 1️⃣ Make sure user is logged in
    if "access_token" not in session:
        return redirect("/login")

    access_token = session["access_token"]

    # 2️⃣ Fetch guilds the user can access
    guilds = requests.get(
        "https://discord.com/api/users/@me/guilds",
        headers={"Authorization": f"Bearer {access_token}"}
    ).json()

    # 3️⃣ Check if user has MANAGE_GUILD permission in this server
    allowed = False
    for g in guilds:
        if int(g["id"]) == guild_id and int(g["permissions"]) & 0x20:
            allowed = True
            break

    if not allowed:
        return "You do not have permission to manage this server."

    # 4️⃣ Make sure bot is actually in the server
    guild = client.get_guild(guild_id)

    if not guild:
        return "Bot is not in this server."

    # 5️⃣ Show server dashboard
    return f"""
    <html>
    <body style="background:#0f1117;color:white;font-family:Arial;padding:40px;">
        <h1>{guild.name}</h1>
        <p>Members: {guild.member_count}</p>
        <p>Channels: {len(guild.channels)}</p>
        <p>Roles: {len(guild.roles)}</p>
        <br>
        <a href="/dashboard" style="color:#5865F2;">← Back</a>
    </body>
    </html>
    """


# ------------------------------
# LOGOUT
# ------------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ------------------------------
# START BOT IN THREAD
# ------------------------------
def run_bot():
    client.run(TOKEN)


bot_thread = threading.Thread(target=run_bot)
bot_thread.daemon = True
bot_thread.start()


# ==============================
# RUN FLASK (Railway uses gunicorn)
# ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)




