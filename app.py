from flask import Flask, redirect, request, render_template_string, Response
import os
import requests
import time
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# --- CONFIG TWITCH ---
CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
REDIRECT_URI = os.environ["REDIRECT_URI"]
DB_URL = os.environ["DATABASE_URL"]

def get_conn():
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)

# --- INIT DB ---
def init_db():
    """Crée les tables nécessaires dans Supabase si elles n'existent pas."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    broadcaster_id TEXT,
                    access_token TEXT,
                    refresh_token TEXT,
                    overlay_key TEXT,
                    last_refresh BIGINT
                )
                """)
                cur.execute("""
                CREATE TABLE IF NOT EXISTS banned_words (
                    id SERIAL PRIMARY KEY,
                    username TEXT,
                    word TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
                """)
            conn.commit()
        print("✅ Tables 'users' et 'banned_words' initialisées.")
    except Exception as e:
        print(f"💥 Erreur init_db: {e}")

init_db()

# --- UTILITAIRES BD ---
def get_user(username):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            return cur.fetchone()

def get_user_by_key(key):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE overlay_key = %s", (key,))
            return cur.fetchone()

def save_user(username, broadcaster_id, access_token, refresh_token):
    now = int(time.time())
    existing = get_user(username)
    overlay_key = existing["overlay_key"] if existing and existing.get("overlay_key") else str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (username, broadcaster_id, access_token, refresh_token, overlay_key, last_refresh)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (username)
                DO UPDATE SET
                    broadcaster_id = EXCLUDED.broadcaster_id,
                    access_token = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    overlay_key = EXCLUDED.overlay_key,
                    last_refresh = EXCLUDED.last_refresh
            """, (username, broadcaster_id, access_token, refresh_token, overlay_key, now))
        conn.commit()
    return overlay_key

def save_banned_words(username, words):
    """Efface et remplace les mots bannis pour un utilisateur."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM banned_words WHERE username = %s", (username,))
            for w in words:
                cur.execute("INSERT INTO banned_words (username, word) VALUES (%s, %s)", (username, w))
        conn.commit()
    print(f"💾 {len(words)} mots enregistrés pour {username}")

# --- TWITCH API ---
def refresh_token(username, refresh_token_value):
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

def get_banned_words(username):
    """Récupère et stocke tous les mots bannis depuis Twitch."""
    user_row = get_user(username)
    if not user_row:
        return "Utilisateur non trouvé.", None

    _, _, _, refresh_token_str, _, _ = user_row.values()
    token, _ = refresh_token(username, refresh_token_str)
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
        r = requests.get("https://api.twitch.tv/helix/moderation/blocked_terms", headers=headers, params=params)
        if r.status_code != 200:
            return f"Erreur Twitch: {r.status_code} {r.text}", None
        data = r.json()
        all_terms.extend(term["text"] for term in data.get("data", []))
        cursor = data.get("pagination", {}).get("cursor")
        if not cursor:
            break

    save_banned_words(username, all_terms)
    return None, all_terms

# --- ROUTES ---
@app.route("/")
def index():
    return render_template_string("""
    <h1>MotInterdit.app</h1>
    <p>Connecte-toi pour activer ton bot et ton overlay OBS.</p>
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

    # échange code contre tokens
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
        return f"Erreur Twitch : {tokens}"

    access_token = tokens["access_token"]
    refresh_token_str = tokens["refresh_token"]

    # infos user
    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {access_token}"
    }
    user_info = requests.get("https://api.twitch.tv/helix/users", headers=headers).json()
    user = user_info["data"][0]
    username = user["login"]
    broadcaster_id = user["id"]

    overlay_key = save_user(username, broadcaster_id, access_token, refresh_token_str)

    return render_template_string(f"""
    <h1>Bienvenue {username} 👋</h1>
    <p>Ton compte est maintenant connecté.</p>
    <p><strong>Commande StreamElements :</strong></p>
    <pre>!addcom !motinterdit C’est le ${{ '{{' }}customapi.{REDIRECT_URI.replace('/callback','')}/api/{username}/count{{ '}}' }}ᵉ mot interdit de la chaîne.</pre>
    <p><strong>URL Overlay OBS :</strong></p>
    <pre>https://{request.host}/overlay?key={overlay_key}</pre>
    <p><strong>URL Overlay OBS "Star Wars crawler" :</strong></p>
    <pre>https://{request.host}/overlay?key={overlay_key}&style=starwars</pre>
    <p>(Ajoute l'une de ces URLs comme source navigateur dans OBS)</p>
    """)

@app.route("/api/<username>/count")
def api_count(username):
    user = get_user(username)
    if not user:
        return f"Utilisateur {username} non enregistré."
    err, words = get_banned_words(username)
    if err:
        return err
    return str(len(words))

@app.route("/overlay")
def overlay():
    key = request.args.get("key")
    style = request.args.get("style", "default")

    if not key:
        return Response("❌ Clé manquante.", status=400)
    user = get_user_by_key(key)
    if not user:
        return Response("❌ Clé invalide.", status=403)

    # Récupération des mots depuis Supabase
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT word FROM banned_words WHERE username = %s ORDER BY word ASC",
                (user["username"],),
            )
            rows = cur.fetchall()

    words = [r["word"] for r in rows]

    # On prépare le texte en dehors du f-string pour éviter tout problème de backslash
    joined_words_html = "<br>".join(words)
    joined_words_text = "\n".join(words)

    # === STYLE STAR WARS ===
    if style.lower() == "starwars":
        html = f"""<!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="utf-8" />
            <title>Star Wars Crawl</title>
            <style>
                html, body {{
                    margin: 0;
                    height: 100%;
                    overflow: hidden;
                    background: radial-gradient(ellipse at bottom, #1b2735 0%, #090a0f 100%);
                    color: #ffe81f;
                    font-family: 'Pathway Gothic One', sans-serif;
                    font-size: 200%;
                    letter-spacing: .15em;
                    perspective: 400px;
                }}
                .fade {{
                    position: relative;
                    width: 100%;
                    min-height: 60vh;
                    top: -100px;
                    background-image: linear-gradient(0deg, transparent, black 75%);
                    z-index: 1;
                }}
                .starwars {{
                    position: relative;
                    height: 800px;
                    color: #ffe81f;
                    font-size: 200%;
                    font-weight: bold;
                    text-align: justify;
                    overflow: hidden;
                    transform-origin: 50% 100%;
                }}
                .crawl {{
                    position: absolute;
                    top: 9999px;
                    transform-origin: 50% 100%;
                    animation: crawl 120s linear infinite;
                }}
                @keyframes crawl {{
                    0% {{
                        top: 100vh;
                        transform: rotateX(25deg)  translateZ(0);
                    }}
                    100% {{
                        top: -6000px;
                        transform: rotateX(25deg) translateZ(-2000px);
                    }}
                }}
                pre {{
                    white-space: pre-line;
                    text-align: center;
                }}
            </style>
        </head>
        <body>
            <div class="fade"></div>
            <section class="starwars">
                <div class="crawl">
                    <pre>{joined_words_html}</pre>
                </div>
            </section>
        </body>
    </html>"""
    return Response(html, mimetype="text/html")

    # === STYLE PAR DÉFAUT (scroll vertical simple) ===
    html = f"""<html>
<body style='background:transparent;color:yellow;font-family:monospace;'>
  <div style='animation:scrollUp 60s linear infinite;height:100vh;overflow:hidden;'>
    <pre>{joined_words_text}</pre>
  </div>
  <style>
    @keyframes scrollUp {{
      0% {{transform:translateY(100%);}}
      100% {{transform:translateY(-100%);}}
    }}
  </style>
</body>
</html>"""
    return Response(html, mimetype="text/html")

@app.route("/refresh_all")
def manual_refresh_all():
    from threading import Thread
    def run_refresh():
        print("🔁 Début du rafraîchissement global des tokens...")
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT username FROM users")
                users = [u["username"] for u in cur.fetchall()]
        for username in users:
            try:
                get_banned_words(username)
            except Exception as e:
                print(f"⚠️ Échec refresh {username}: {e}")
        print("✅ Rafraîchissement global terminé.")

    Thread(target=run_refresh).start()
    return Response("OK", mimetype="text/plain")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
