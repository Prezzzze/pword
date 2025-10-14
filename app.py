from flask import Flask
import os
import requests

app = Flask(__name__)

# Les variables d'environnement doivent être configurées sur Render
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_ACCESS_TOKEN = os.getenv("TWITCH_ACCESS_TOKEN")
BROADCASTER_ID = os.getenv("BROADCASTER_ID")  # ton ID de chaîne Twitch

@app.route("/")
def home():
    return "API motinterdit opérationnelle ✅"

@app.route("/mots/count")
def count_banned_words():
    """Renvoie le nombre de mots bannis sur la chaîne Twitch."""
    if not (TWITCH_CLIENT_ID and TWITCH_ACCESS_TOKEN and BROADCASTER_ID):
        return "Configuration manquante : vérifie tes variables d'environnement Render."

    url = f"https://api.twitch.tv/helix/moderation/blocked_terms"
    params = {
        "broadcaster_id": BROADCASTER_ID,
        "moderator_id": BROADCASTER_ID
    }
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {TWITCH_ACCESS_TOKEN}"
    }

    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        return f"Erreur Twitch API ({resp.status_code}): {resp.text}"

    data = resp.json()
    words = [term["text"] for term in data.get("data", [])]
    return str(len(words))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
