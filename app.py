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
    write_token_
