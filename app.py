from flask import Flask
import os
import requests
import time

app = Flask(__name__)

# Variables d'environnement sur Render
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
BROADCASTER_ID = os.getenv("BROADCASTER_ID")

# Ces deux valeurs seront stockées et mises à jour automatiquement
ACCESS_TOKEN_FILE = "access_token.txt"
REFRESH_TOKEN_FILE = "refresh_token.txt"


def read_token(file):
    if os.path.exists(file):
        with open(file, "r") as f:
            return f.read().strip()
    return None


def write_token(file, value):
    with open(file, "w") as f:
        f.write(value.strip())


def refresh_access_token():
    """Utilise le refresh token pour obtenir un nouveau token d'accès"""
    refresh_token = read_token(REFRESH_TOKEN_FILE)
    if not refresh_token:
        return None, "Aucun refresh token trouvé."

    url = "https://id.twitch.tv/oauth2/token"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
    }

    resp = requests.post(url, data=payload)
    if resp.status_code != 200:
        return None, f"Erreur refresh token: {resp.text}"

    data = resp.json()
    access_token = data["access_token"]
    refresh_token = data.get("refresh_token", refresh_token)

    write_token(ACCESS_TOKEN_FILE, access_token)
    write_token(REFRESH_TOKEN_FILE, refresh_token)

    print("✅ Token Twitch rafraîchi avec succès.")
    return access_token, None


def get_access_token():
    """Retourne un token valide, rafraîchit si nécessaire"""
    token = read_token(ACCESS_TOKEN_FILE)
    if not token:
        new_token, err = refresh_access_token()
        if err:
            print(err)
        return new_token
    return token


def get_banned_words():
    """Récupère les mots bannis via l'API Twitch"""
    token = get_access_token()
    if not token:
        return [], "Token manquant ou invalide."

    url = "https://api.twitch.tv/helix/moderation/blocked_terms"
    params = {
        "broadcaster_id": BROADCASTER_ID,
        "moderator_id": BROADCASTER_ID
    }
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }

    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code == 401:
        # Token expiré → on tente un refresh
        print("⚠️ Token expiré, rafraîchissement en cours...")
        refresh_access_token()
        return get_banned_words()

    if resp.status_code != 200:
        return [], f"Erreur API Twitch ({resp.status_code}): {resp.text}"

    data = resp.json()
    return [term["text"] for term in data.get("data", [])], None


@app.route("/")
def home():
    return "API Pword avec refresh automatique ✅"


@app.route("/mots/count")
def mots_count():
    words, err = get_banned_words()
    if err:
        return err
    return str(len(words))


@app.route("/refresh")
def manual_refresh():
    token, err = refresh_access_token()
    return err or f"Nouveau token : {token[:10]}..."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
