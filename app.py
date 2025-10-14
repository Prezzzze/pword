import requests
import os

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_ACCESS_TOKEN = os.getenv("TWITCH_ACCESS_TOKEN")
BROADCASTER_ID = os.getenv("BROADCASTER_ID")

def get_banned_words():
    url = f"https://api.twitch.tv/helix/moderation/blocked_terms?broadcaster_id={BROADCASTER_ID}&moderator_id={BROADCASTER_ID}"
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {TWITCH_ACCESS_TOKEN}"
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print("Erreur API Twitch:", resp.text)
        return []
    data = resp.json()
    return [term["text"] for term in data.get("data", [])]
