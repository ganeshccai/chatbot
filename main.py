from datetime import datetime, timedelta
import os
from threading import Lock
from flask import Flask, request, jsonify, redirect, url_for
from flask_cors import CORS

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "temp_key")
CORS(app, origins=["https://ganeshccai.github.io"], supports_credentials=True)

CHAT_ID = "1234"
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
    chat_id, sender, text = data.get("chat_id"), data.get("sender"), data.get("text")
    timestamp = datetime.utcnow().isoformat() + "Z"
    with _store_lock:
        all_chats.setdefault(chat_id, []).append({
            "chat_id": chat_id,
            "sender": sender,
            "text": text,
            "timestamp": timestamp,
            "seen_by": None
        })
        live_typing[chat_id] = {"sender": "", "text": "", "timestamp": 0}
    return jsonify({"status": "ok"})

@app.route("/messages/<chat_id>", methods=["GET"])
def get_messages(chat_id):
    viewer = request.args.get("viewer")
    cutoff = datetime.utcnow() - timedelta(minutes=1)
    with _store_lock:
        messages = all_chats.get(chat_id, [])
        filtered = [m for m in messages if datetime.fromisoformat(m["timestamp"].replace("Z", "")) > cutoff]
        all_chats[chat_id] = filtered
        if filtered:
            last_msg = filtered[-1]
            if last_msg["sender"] != viewer:
                last_msg["seen_by"] = viewer
        return jsonify(filtered)

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
    chat_id, sender = data.get("chat_id"), data.get("sender")
    with _store_lock:
        if sender == "user":
            online_users[chat_id] = True
        elif sender == "agent":
            online_users["agent"] = True
    return jsonify({"status": "ok"})

@app.route("/live_typing", methods=["POST"])
def update_live_typing():
    data = request.get_json(silent=True)
    chat_id, sender, text = data.get("chat_id"), data.get("sender"), data.get("text", "")
    with _store_lock:
        live_typing[chat_id] = {
            "sender": sender,
            "text": text,
            "timestamp": datetime.utcnow().timestamp()
        }
    return jsonify({"status": "ok"})

@app.route("/get_live_typing/<chat_id>", methods=["GET"])
def get_live_typing(chat_id):
    with _store_lock:
        typing = live_typing.get(chat_id, {"sender": "", "text": "", "timestamp": 0})
        if datetime.utcnow().timestamp() - typing.get("timestamp", 0) > 5:
            return jsonify({"sender": "", "text": ""})
        return jsonify(typing)

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
        live_typing[chat_id] = {"sender": "", "text": "", "timestamp": 0}
    return jsonify({"status": "ok"})

@app.route("/logout_agent", methods=["POST"])
def logout_agent():
    with _store_lock:
        online_users["agent"] = False
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
