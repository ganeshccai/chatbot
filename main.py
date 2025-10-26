from datetime import datetime, timedelta
import os
from threading import Lock
from uuid import uuid4
from flask import Flask, request, jsonify, redirect, url_for
from flask_cors import CORS

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "temp_key")
CORS(app, origins=["https://ganeshccai.github.io"], supports_credentials=True)

CHAT_ID = "1234"
all_chats = {}
online_users = {}
live_typing = {}
last_seen = {}
active_sessions = {}  # key = f"{chat_id}:{sender}" → token
_store_lock = Lock()

SESSION_TIMEOUT = timedelta(seconds=2)

def is_valid_session(chat_id, sender):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    key = f"{chat_id}:{sender}"
    return active_sessions.get(key) == token

@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("status"))

@app.route("/status", methods=["GET"])
def status():
    return jsonify({"status": "running"})

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    chat_id = data.get("chat_id")
    password = data.get("password")
    sender = data.get("sender", "user")

    if password != "1":
        return jsonify({"success": False, "error": "Wrong password"}), 403

    with _store_lock:
        key = f"{chat_id}:{sender}"
        last = last_seen.get(sender)
        if key in active_sessions:
            if not last or datetime.utcnow() - last > SESSION_TIMEOUT:
                active_sessions.pop(key, None)  # Expired session
            else:
                return jsonify({"success": False, "error": "Session already active"}), 403

        token = str(uuid4())
        active_sessions[key] = token
        online_users[sender] = True
        last_seen[sender] = datetime.utcnow()

    return jsonify({"success": True, "session_token": token})

@app.route("/send", methods=["POST"])
def send_message():
    data = request.get_json(silent=True)
    chat_id = data.get("chat_id")
    sender = data.get("sender")
    text = data.get("text")

    if not is_valid_session(chat_id, sender):
        return jsonify({"error": "Invalid session"}), 403

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
    active = request.args.get("active") == "true"
    with _store_lock:
        messages = all_chats.get(chat_id, [])
        if messages and active:
            last_msg = messages[-1]
            if last_msg["sender"] != viewer:
                last_msg["seen_by"] = viewer
        return jsonify(messages)

@app.route("/is_online/<chat_id>", methods=["GET"])
def is_online(chat_id):
    now = datetime.utcnow()
    with _store_lock:
        user_active = (
            online_users.get(chat_id, False) and
            last_seen.get(chat_id) and
            now - last_seen[chat_id] < SESSION_TIMEOUT
        )
        agent_active = (
            online_users.get("agent", False) and
            last_seen.get("agent") and
            now - last_seen["agent"] < SESSION_TIMEOUT
        )
        return jsonify({
            "user_online": user_active,
            "agent_online": agent_active
        })

@app.route("/mark_online", methods=["POST"])
def mark_online():
    data = request.get_json(silent=True) or {}
    chat_id = data.get("chat_id")
    sender = data.get("sender")

    if not is_valid_session(chat_id, sender):
        return jsonify({"error": "Invalid session"}), 403

    now = datetime.utcnow()
    with _store_lock:
        online_users[sender] = True
        last_seen[sender] = now
    return jsonify({"status": "ok"})

@app.route("/live_typing", methods=["POST"])
def update_live_typing():
    data = request.get_json(silent=True)
    chat_id = data.get("chat_id")
    sender = data.get("sender")
    text = data.get("text", "")

    if not is_valid_session(chat_id, sender):
        return jsonify({"error": "Invalid session"}), 403

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
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    sender = "agent" if f"{chat_id}:agent" in active_sessions and active_sessions[f"{chat_id}:agent"] == token else "user"
    if not is_valid_session(chat_id, sender):
        return jsonify({"error": "Invalid session"}), 403

    with _store_lock:
        all_chats[chat_id] = []
    return jsonify({"status": "cleared"})

@app.route("/logout_user", methods=["POST"])
def logout_user():
    data = request.get_json(silent=True) or {}
    chat_id = data.get("chat_id") or CHAT_ID
    key = f"{chat_id}:user"
    with _store_lock:
        print(f"Logout received for {key}")
        online_users[chat_id] = False
        live_typing[chat_id] = {"sender": "", "text": "", "timestamp": 0}
        active_sessions.pop(key, None)
    return jsonify({"status": "ok"})

@app.route("/logout_agent", methods=["POST"])
def logout_agent():
    data = request.get_json(silent=True) or {}
    chat_id = data.get("chat_id") or CHAT_ID
    key = f"{chat_id}:agent"
    with _store_lock:
        print(f"Logout received for {key}")
        online_users["agent"] = False
        active_sessions.pop(key, None)
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
