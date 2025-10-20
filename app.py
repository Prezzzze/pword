from flask import Flask, redirect, request, render_template_string, Response
import os
import sqlite3
import requests
import time
import threading
import sys

app = Flask(__name__)

# --- CONFIG TWITCH ---
CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://tonapp.onrender.com/callback")

# --- BASE DE DONNÉES ---
DB_PATH = os.path.join("/tmp", "users.db")

def init_db():
    """Initialise la base SQLite dans /tmp si elle n'existe pas."""
    if not os.path.exists(DB_PATH):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                broadcaster_id TEXT,
                access_token TEXT,
                refresh_token TEXT,
                last_refresh INTEGER
            )
            """)
        print("✅ Nouvelle base users.db initialisée dans /tmp")
    else:
        print("📂 Base existante trouvée dans /tmp")
init_db()

# --- OUTILS BD ---
def get_user(username):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT * FROM users WHERE username=?", (username,))
        return cur.fetchone()

def save_user(username, broadcaster_id, access_token, refresh_token):
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
        INSERT OR REPLACE INTO users (username, broadcaster_id, access_token, refresh_token, last_refresh)
        VALUES (?, ?, ?, ?, ?)
        """, (username, broadcaster_id, access_token, refresh_token, now))
    sys.stdout.write(f"💾 Sauvegarde utilisateur {username} (token mis à jour)\n")

# --- TWITCH API ---
def refresh_token(username, refresh_token_value):
    """Rafraîchit un token Twitch pour un utilisateur donné."""
    url = "https://id.twitch.tv/oauth2/token"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_value,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    resp = requests.post(url, data=payload)
    if resp.status_code != 200:
        sys.stdout.write(f"⚠️ Erreur de refresh pour {username}: {resp.text}\n")
        return None, None

    data = resp.json()
    new_access = data["access_token"]
    new_refresh = data.get("refresh_token", refresh_token_value)
    save_user(username, get_user(username)[1], new_access, new_refresh)
    sys.stdout.write(f"✅ Token rafraîchi pour {username}\n")
    return new_access, new_refresh

def refresh_all_tokens():
    """Rafraîchit tous les tokens Twitch de la base (silencieux côté HTTP)."""
    sys.stdout.write("🔁 Début du rafraîchissement global des tokens...\n")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute("SELECT username, refresh_token FROM users")
            users = cur.fetchall()

        for username, refresh_token_str in users:
            try:
                refresh_token(username, refresh_token_str)
            except Exception as e:
                sys.stdout.write(f"⚠️ Refresh échoué pour {username}: {e}\n")
                continue

        sys.stdout.write(f"✅ Rafraîchissement global terminé ({len(users)} comptes).\n")
    except Exception as e:
        sys.stdout.write(f"💥 Erreur globale lors du refresh_all: {e}\n")

def get_banned_words(user):
    """Récupère tous les mots bannis via l'API Twitch, avec pagination."""
    _, _, _, refresh_token_str, _ = get_user(user)
    token, _ = refresh_token(user, refresh_token_str)
    broadcaster_id = get_user(user)[1]

    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }

    all_terms = []
    cursor = None

    while True:
        params = {
            "broadcaster_id": broadcaster_id,
            "moderator_id": broadcaster_id,
            "first": 100
        }
        if cursor:
            params["after"] = cursor

        r = requests.get("https://api.twitch.tv/helix/moderation/blocked_terms",
                         headers=headers, params=params)

        if r.status_code == 401:
            sys.stdout.write(f"⚠️ Token expiré pour {user}, tentative de refresh...\n")
            token, _ = refresh_token(user, refresh_token_str)
            headers["Authorization"] = f"Bearer {token}"
            continue

        if r.status_code != 200:
            return f"Erreur Twitch: {r.status_code} {r.text}", None

        data = r.json()
        all_terms.extend(term["text"] for term in data.get("data", []))
        cursor = data.get("pagination", {}).get("cursor")
        if not cursor:
            break

    sys.stdout.write(f"📦 {len(all_terms)} mots interdits récupérés pour {user}\n")
    return None, all_terms

# --- ROUTES FLASK ---
@app.route("/")
def index():
    return render_template_string("""
    <h1>MotInterdit.app</h1>
    <p>Connecte-toi pour activer ta commande Twitch !</p>
    <a href="/login">🔑 Se connecter avec Twitch</a>
    """)

@app.route("/login")
def login():
    scope = "moderator:read:blocked_terms user:read:email"
    auth_url = (
        f"https://id.twitch.tv/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scope}"
    )
    return redirect(auth_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Erreur : aucun code reçu."

    token_url = "https://id.twitch.tv/oauth2/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI
    }
    r = requests.post(token_url, data=data)
    tokens = r.json()

    if "access_token" not in tokens:
        return f"Erreur lors de l'autorisation Twitch : {tokens}"

    access_token = tokens["access_token"]
    refresh_token_str = tokens["refresh_token"]

    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {access_token}"
    }
    user_info = requests.get("https://api.twitch.tv/helix/users", headers=headers).json()
    user = user_info["data"][0]
    username = user["login"]
    broadcaster_id = user["id"]

    save_user(username, broadcaster_id, access_token, refresh_token_str)

    return render_template_string(f"""
    <h1>Bienvenue {username} 👋</h1>
    <p>Ton compte est maintenant connecté !</p>
    <p>Colle cette commande dans StreamElements :</p>
    <pre>!addcom !motinterdit C’est le ${{customapi.{REDIRECT_URI.replace('/callback','')}/api/{username}/count}}ᵉ mot interdit de la chaîne.</pre>
    """)

@app.route("/api/<username>/count")
def api_count(username):
    user = get_user(username)
    if not user:
        return f"Utilisateur {username} non enregistré. Va sur /login pour te connecter."
    err, words = get_banned_words(username)
    if err:
        return err
    return str(len(words))

@app.route("/refresh_all")
def manual_refresh_all():
    """Déclenche le rafraîchissement global en tâche de fond (cron ultra-silencieux)."""
    def background_job():
        try:
            refresh_all_tokens()
        except Exception as e:
            sys.stdout.write(f"💥 Erreur lors du refresh_all: {e}\n")

    threading.Thread(target=background_job, daemon=True).start()
    # Réponse 100 % minimale sans aucun contenu HTML ni entête superflu
    return Response("OK", status=200, mimetype="text/plain")

# --- MAIN ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
