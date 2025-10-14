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



from flask import Flask, request, render_template_string, redirect
import os

app = Flask(__name__)

WORD_FILE = "PWord.txt"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>PWords</title>
    <style>
        body { font-family: sans-serif; background-color: #121212; color: #eee; text-align: center; margin-top: 50px; }
        input, button { padding: 8px; font-size: 16px; }
        ul { list-style: none; padding: 0; max-width: 400px; margin: 20px auto; text-align: left; }
        li { background: #1e1e1e; margin: 4px 0; padding: 6px 10px; border-radius: 6px; }
        .count { font-weight: bold; margin-bottom: 10px; }
        form { margin-top: 20px; }
    </style>
</head>
<body>
    <h1>Liste des PWords</h1>
    <p class="count">Actuellement {{ count }} PWords</p>

    <form action="/add" method="post">
        <input type="text" name="word" placeholder="Nouveau PWord" required>
        <button type="submit">Ajouter</button>
    </form>

    <ul>
        {% for word in words %}
            <li>{{ loop.index }} — {{ word }}</li>
        {% endfor %}
    </ul>
</body>
</html>
"""

@app.route("/")
def home():
    if not os.path.exists(WORD_FILE):
        open(WORD_FILE, "w", encoding="utf-8").close()

    with open(WORD_FILE, encoding="utf-8") as f:
        words = [w.strip() for w in f if w.strip()]
    return render_template_string(HTML_TEMPLATE, words=words, count=len(words))


@app.route("/add", methods=["POST"])
def add_word():
    word = request.form.get("word", "").strip()
    if word:
        with open(WORD_FILE, "a", encoding="utf-8") as f:
            f.write(word + "\n")
    return redirect("/")


@app.route("/mots/count")
def count_words():
    if not os.path.exists(WORD_FILE):
        return "0"
    with open(WORD_FILE, encoding="utf-8") as f:
        count = sum(1 for line in f if line.strip())
    return str(count)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
