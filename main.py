from flask import Flask, render_template, request, session, jsonify
from flask_cors import CORS

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = "temp_key"
CORS(app)

CHAT_ID = "1234"
CHAT_PASSWORD = "1"

# In-memory stores
all_chats = {}
online_users = {}
live_typing = {}


# ---------------- User Page ----------------
@app.route("/user", methods=["GET", "POST"])
def user_page():
    if request.method == "POST":
        password = request.form.get("password")
        if password == CHAT_PASSWORD:
            session["chat_id"] = CHAT_ID
            all_chats[CHAT_ID] = []
            online_users[CHAT_ID] = True  # user online
            live_typing[CHAT_ID] = ""
            return render_template("user.html")
        return "Wrong password"
    return """<form method="post">
                <input type="password" name="password" placeholder="*****"/>
                <input type="submit" value="➤"/>
              </form>"""


# ---------------- Agent Page ----------------
@app.route("/agent", methods=["GET", "POST"])
def agent_page():
    if request.method == "POST":
        password = request.form.get("password")
        if password == CHAT_PASSWORD:
            online_users["agent"] = True  # mark agent online
            return render_template("agent.html")
        return "Wrong password"
    return """<form method="post">
                <input type="password" name="password" placeholder="Enter Password"/>
                <input type="submit" value="Login"/>
              </form>"""


# ---------------- Send Message ----------------
@app.route("/send", methods=["POST"])
def send_message():
    data = request.get_json()
    chat_id = data.get("chat_id")
    all_chats.setdefault(chat_id, []).append(data)
    return jsonify({"status": "ok"})


# ---------------- Get Messages ----------------
@app.route("/messages/<chat_id>")
def get_messages(chat_id):
    return jsonify(all_chats.get(chat_id, []))


# ---------------- Online Status ----------------
@app.route("/is_online/<chat_id>")
def is_online(chat_id):
    user_online = online_users.get(chat_id, False)
    agent_online = online_users.get("agent", False)
    return jsonify(
        {
            "user_online": user_online,
            "online": agent_online,  # keep 'online' for backward compatibility
        }
    )


# ---------------- Live Typing ----------------
@app.route("/live_typing", methods=["POST"])
def update_live_typing():
    data = request.get_json()
    chat_id = data.get("chat_id")
    text = data.get("text", "")
    live_typing[chat_id] = text.strip()
    return jsonify({"status": "ok"})


@app.route("/get_live_typing/<chat_id>")
def get_live_typing(chat_id):
    return jsonify({"text": live_typing.get(chat_id, "")})


# ---------------- Logout Handlers ----------------
@app.route("/logout_user", methods=["POST"])
def logout_user():
    data = request.get_json(force=True, silent=True) or {}
    chat_id = data.get("chat_id", CHAT_ID)
    online_users[chat_id] = False
    live_typing[chat_id] = ""
    return jsonify({"status": "ok"})


@app.route("/logout_agent", methods=["POST"])
def logout_agent():
    online_users["agent"] = False
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
