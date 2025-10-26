# app.py
from datetime import datetime
import os
from threading import Lock
from flask import Flask, request, jsonify, redirect, url_for
from flask_cors import CORS

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "temp_key")

# Allow calls from your GitHub Pages domain
CORS(app, origins=["https://ganeshccai.github.io"], supports_credentials=True)

CHAT_ID = "1234"

# In‑memory stores
all_chats = {}
online_users = {}
live_typing = {}
_store_lock = Lock()

@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("status"))

@app.route("/status", methods=["GET"])
def status():
    return jsonify({"status": "running"})

@app.route("/send", methods=["POST"])
def send_message():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    chat_id, sender, text = data.get("chat_id"), data.get("sender"), data.get("text")
    if not chat_id or not sender or text is None:
        return jsonify({"error": "Missing fields"}), 400
    timestamp = datetime.utcnow().isoformat() + "Z"
    with _store_lock:
        all_chats.setdefault(chat_id, []).append({
            "chat_id": chat_id,
            "sender": sender,
            "text": text,
            "timestamp": timestamp
        })
        # Clear typing once a message is sent
        live_typing[chat_id] = {"sender": "", "text": ""}
    return jsonify({"status": "ok"})

@app.route("/messages/<chat_id>", methods=["GET"])
def get_messages(chat_id):
    with _store_lock:
        return jsonify(list(all_chats.get(chat_id, [])))

@app.route("/is_online/<chat_id>", methods=["GET"])
def is_online(chat_id):
    with _store_lock:
        return jsonify({
            "user_online": online_users.get(chat_id, False),
            "agent_online": online_users.get("agent", False)
        })

@app.route("/mark_online", methods=["POST"])
def mark_online():
    data = request.get_json(silent=True) or {}
    chat_id = data.get("chat_id")
    sender = data.get("sender")
    if not chat_id or not sender:
        return jsonify({"error": "missing"}), 400
    with _store_lock:
        if sender == "user":
            online_users[chat_id] = True
        elif sender == "agent":
            online_users["agent"] = True
    return jsonify({"status": "ok"})

@app.route("/live_typing", methods=["POST"])
def update_live_typing():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    chat_id, sender, text = data.get("chat_id"), data.get("sender"), data.get("text", "")
    if not chat_id or not sender:
        return jsonify({"error": "Missing fields"}), 400
    with _store_lock:
        live_typing[chat_id] = {"sender": sender, "text": text}
    return jsonify({"status": "ok"})

@app.route("/get_live_typing/<chat_id>", methods=["GET"])
def get_live_typing(chat_id):
    with _store_lock:
        return jsonify(live_typing.get(chat_id, {"sender": "", "text": ""}))

@app.route("/clear_chat/<chat_id>", methods=["POST"])
def clear_chat(chat_id):
    with _store_lock:
        all_chats[chat_id] = []
    return jsonify({"status": "cleared"})

@app.route("/logout_user", methods=["POST"])
def logout_user():
    data = request.get_json(silent=True) or {}
    chat_id = data.get("chat_id") or CHAT_ID
    with _store_lock:
        online_users[chat_id] = False
        live_typing[chat_id] = {"sender": "", "text": ""}
    return jsonify({"status": "ok"})

@app.route("/logout_agent", methods=["POST"])
def logout_agent():
    with _store_lock:
        online_users["agent"] = False
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    # Run locally on port 8080
    app.run(host="0.0.0.0", port=8080)
