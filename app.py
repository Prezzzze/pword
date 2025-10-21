from flask import Flask, redirect, request, render_template_string, Response
import os
import requests
import time
import sys
import subprocess
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# --- CONFIG TWITCH ---
CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://tonapp.onrender.com/callback")

# --- CONFIG SUPABASE ---
DB_URL = os.getenv("DATABASE_URL")  # ex: postgresql://postgres:pwd@db.xxx.supabase.co:5432/postgres

def get_conn():
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)

# --- INIT DB ---
def init_db():
    """Crée la table users si elle n'existe pas."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    broadcaster_id TEXT,
                    access_token TEXT,
                    refresh_token TEXT,
                    last_refresh BIGINT
                )
                """)
            conn.commit()
        print("✅ Base Supabase initialisée.")
    except Exception as e:
        print(f"💥 Erreur init_db: {e}")

init_db()

# --- UTILITAIRES BD ---
def get_user(username):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                return cur.fetchone()
    except Exception as e:
        print(f"⚠️ get_user({username}) échoué : {e}")
        return None

def save_user(username, broadcaster_id, access_token, refresh_token):
    now = int(time.time())
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO users (username, broadcaster_id, access_token, refresh_token, last_refresh)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (username)
                    DO UPDATE SET
                        broadcaster_id = EXCLUDED.broadcaster_id,
                        access_token = EXCLUDED.access_token,
                        refresh_token = EXCLUDED.refresh_token,
                        last_refresh = EXCLUDED.last_refresh
                """, (username, broadcaster_id, access_token, refresh_token, now))
            conn.commit()
        print(f"💾 Utilisateur {username} enregistré / mis à jour dans Supabase.")
    except Exception as e:
        print(f"💥 Erreur save_user: {e}")

def get_all_users():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT username, refresh_token FROM users")
                return cur.fetchall()
    except Exception as e:
        print(f"⚠️ get_all_users échoué : {e}")
        return []

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
        print(f"⚠️ Erreur de refresh pour {username}: {resp.text}")
        return None, None

    data = resp.json()
    new_access = data["access_token"]
    new_refresh = data.get("refresh_token", refresh_token_value)
    user = get_user(username)
    if user:
        save_user(username, user["broadcaster_id"], new_access, new_refresh)
    print(f"✅ Token rafraîchi pour {username}")
    return new_access, new_refresh

def refresh_all_tokens():
    """Rafraîchit tous les tokens Twitch de la base."""
    print("🔁 Début du rafraîchissement global des tokens...")
    users = get_all_users()
    total = 0

    for u in users:
        username = u["username"]
        refresh_token_str = u["refresh_token"]
        try:
            refresh_token(username, refresh_token_str)
            total += 1
        except Exception as e:
            print(f"⚠️ Refresh échoué pour {username}: {e}")

    print(f"✅ Rafraîchissement global terminé ({total} comptes).")

def get_banned_words(user):
    """Récupère tous les mots bannis via l'API Twitch, avec pagination."""
    user_row = get_user(user)
    if not user_row:
        return "Utilisateur non trouvé.", None

    _, _, _, refresh_token_str, _ = user_row.values()
    token, _ = refresh_token(user, refresh_token_str)
    broadcaster_id = user_row["broadcaster_id"]

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
            print(f"⚠️ Token expiré pour {user}, tentative de refresh...")
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

    print(f"📦 {len(all_terms)} mots interdits récupérés pour {user}")
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
    """Lance le refresh global en subprocess pour éviter tout redémarrage Render."""
    try:
        subprocess.Popen(
            ["python3", "-c", "import app; app.refresh_all_tokens()"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        sys.stdout.write("🚀 Refresh global lancé en sous-processus.\n")
    except Exception as e:
        sys.stdout.write(f"💥 Erreur lancement subprocess: {e}\n")
        return Response("ERROR", status=500, mimetype="text/plain")

    return Response("OK", status=200, mimetype="text/plain")

# --- MAIN ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
