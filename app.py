from flask import Flask
import os

app = Flask(__name__)

# Fichier contenant ta liste de mots interdits
WORD_FILE = "PWord.txt"

@app.route("/")
def home():
    return "API PWord opérationnelle ✅"

@app.route("/mots/count")
def count_words():
    if not os.path.exists(WORD_FILE):
        return "0"  # si le fichier n'existe pas encore
    with open(WORD_FILE, encoding="utf-8") as f:
        count = sum(1 for line in f if line.strip())
    return str(count)

if __name__ == "__main__":
    # Render définit le port dans la variable d'environnement PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
