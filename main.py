from datetime import datetime
import os
from threading import Lock

from flask import Flask, render_template, request, session, jsonify, redirect, url_for
from flask_cors import CORS

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "temp_key")
CORS(app, supports_credentials=True)

CHAT_ID = "1234"
CHAT_PASSWORD = "1"

all_chats = {}
online_users = {}
live_typing = {}

_store_lock = Lock()


@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("user_page"))


@app.route("/user", methods=["GET", "POST"])
def user_page():
    if request.method == "POST":
        password = request.form.get("password")
        if password == CHAT_PASSWORD:
            session["chat_id"] = CHAT_ID
            with _store_lock:
                all_chats.setdefault(CHAT_ID, [])
                online_users[CHAT_ID] = True
                live_typing.setdefault(CHAT_ID, {"sender": "", "text": ""})
            return render_template("user.html")
        return "Wrong password", 401
    return """<form method="post" style="display:flex;justify-content:center;align-items:center;height:100vh;flex-direction:column;font-family:Arial;">
                <h2>User Login</h2>
                <input type="password" name="password" placeholder="Enter Password" style="padding:10px;margin:10px;border-radius:5px;border:1px solid #ccc;"/>
                <input type="submit" value="Login" style="padding:10px 20px;background:#ff5f6d;color:white;border:none;border-radius:5px;cursor:pointer;"/>
              </form>"""


@app.route("/agent", methods=["GET", "POST"])
def agent_page():
    if request.method == "POST":
        password = request.form.get("password")
        if password == CHAT_PASSWORD:
            with _store_lock:
                online_users["agent"] = True
                all_chats.setdefault(CHAT_ID, [])
                live_typing.setdefault(CHAT_ID, {"sender": "", "text": ""})
            return render_template("agent.html")
        return "Wrong password", 401
    return """<form method="post" style="display:flex;justify-content:center;align-items:center;height:100vh;flex-direction:column;font-family:Arial;">
                <h2>Agent Login</h2>
                <input type="password" name="password" placeholder="Enter Password" style="padding:10px;margin:10px;border-radius:5px;border:1px solid #ccc;"/>
                <input type="submit" value="Login" style="padding:10px 20px;background:#ff5f6d;color:white;border:none;border-radius:5px;cursor:pointer;"/>
              </form>"""


@app.route("/send", methods=["POST"])
def send_message():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid or missing JSON payload"}), 400

    chat_id = data.get("chat_id")
    sender = data.get("sender")
    text = data.get("text")
    if not chat_id or not sender or text is None:
        return jsonify({"error": "Missing required fields: chat_id, sender, text"}), 400

    if "timestamp" not in data:
        data["timestamp"] = datetime.utcnow().isoformat() + "Z"

    with _store_lock:
        all_chats.setdefault(chat_id, []).append({
            "chat_id": chat_id,
            "sender": sender,
            "text": text,
            "timestamp": data["timestamp"],
        })
        live_typing[chat_id] = {"sender": "", "text": ""}

    return jsonify({"status": "ok"})


@app.route("/messages/<chat_id>", methods=["GET"])
def get_messages(chat_id):
    with _store_lock:
        msgs = list(all_chats.get(chat_id, []))
    return jsonify(msgs)


@app.route("/is_online/<chat_id>", methods=["GET"])
def is_online(chat_id):
    with _store_lock:
        user_online = online_users.get(chat_id, False)
        agent_online = online_users.get("agent", False)
    return jsonify({
        "user_online": user_online,
        "agent_online": agent_online,
        "online": agent_online,
    })


@app.route("/live_typing", methods=["POST"])
def update_live_typing():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid or missing JSON payload"}), 400

    chat_id = data.get("chat_id")
    sender = data.get("sender")
    text = data.get("text", "")

    if not chat_id or not sender:
        return jsonify({"error": "Missing required fields: chat_id, sender"}), 400

    if not isinstance(text, str):
        text = str(text)

    with _store_lock:
        live_typing[chat_id] = {"sender": sender, "text": text.strip()}

    return jsonify({"status": "ok"})


@app.route("/get_live_typing/<chat_id>", methods=["GET"])
def get_live_typing(chat_id):
    with _store_lock:
        obj = live_typing.get(chat_id, {"sender": "", "text": ""})
    if not isinstance(obj, dict):
        obj = {"sender": "", "text": ""}
    return jsonify(obj)


@app.route("/logout_user", methods=["POST"])
def logout_user():
    data = request.get_json(silent=True) or {}
    chat_id = data.get("chat_id") or session.get("chat_id") or CHAT_ID
    with _store_lock:
        online_users[chat_id] = False
        live_typing[chat_id] = {"sender": "", "text": ""}
    session.pop("chat_id", None)
    return jsonify({"status": "ok"})


@app.route("/logout_agent", methods=["POST"])
def logout_agent():
    with _store_lock:
        online_users["agent"] = False
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
