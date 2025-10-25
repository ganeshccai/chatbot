from flask import Flask, render_template, request, jsonify, Response, stream_with_context, session
from flask_cors import CORS
import queue
import json
import time

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = "temp_key"
CORS(app)

CHAT_ID = "1234"
CHAT_PASSWORD = "1"

# Stores
all_chats = {}           # chat_id -> list of messages
online_users = {}        # chat_id or 'agent' -> True/False
live_typing = {}         # chat_id -> text
sse_subscribers = {}     # chat_id -> [queues]

# ---------------- UTIL ----------------
def broadcast(chat_id, data):
    """Send event data to all subscribers."""
    msg = json.dumps(data)
    for q in list(sse_subscribers.get(chat_id, [])):
        try:
            q.put_nowait(msg)
        except Exception:
            pass

# ---------------- USER PAGE ----------------
@app.route("/user", methods=["GET", "POST"])
def user_page():
    if request.method == "POST":
        pwd = request.form.get("password")
        if pwd == CHAT_PASSWORD:
            session["chat_id"] = CHAT_ID
            # clear old chat
            all_chats[CHAT_ID] = []
            live_typing[CHAT_ID] = ""
            online_users[CHAT_ID] = True
            return render_template("user.html")
        return "Wrong password"
    return """<form method="post">
                <input type="password" name="password" placeholder="Password"/>
                <input type="submit" value="Login"/>
              </form>"""

# ---------------- AGENT PAGE ----------------
@app.route("/agent", methods=["GET", "POST"])
def agent_page():
    if request.method == "POST":
        pwd = request.form.get("password")
        if pwd == CHAT_PASSWORD:
            online_users["agent"] = True
            return render_template("agent.html")
        return "Wrong password"
    return """<form method="post">
                <input type="password" name="password" placeholder="Password"/>
                <input type="submit" value="Login"/>
              </form>"""

# ---------------- SEND MESSAGE ----------------
@app.route("/send", methods=["POST"])
def send_message():
    data = request.get_json(force=True)
    chat_id = data.get("chat_id")
    sender = data.get("sender")
    text = (data.get("text") or "").strip()
    if not chat_id or not sender or not text:
        return jsonify({"status": "error", "message": "chat_id, sender, text required"}), 400

    msgs = all_chats.setdefault(chat_id, [])
    msg_id = len(msgs)
    msg = {"id": msg_id, "sender": sender, "text": text, "seen_by": []}
    msgs.append(msg)

    broadcast(chat_id, {"type": "new_message", "message": msg})
    return jsonify({"status": "ok", "id": msg_id})

# ---------------- GET MESSAGES ----------------
@app.route("/messages/<chat_id>")
def get_messages(chat_id):
    return jsonify(all_chats.get(chat_id, []))

# ---------------- ONLINE STATUS ----------------
@app.route("/is_online/<chat_id>")
def is_online(chat_id):
    return jsonify({
        "user_online": online_users.get(chat_id, False),
        "online": online_users.get("agent", False)
    })

# ---------------- LIVE TYPING ----------------
@app.route("/live_typing", methods=["POST"])
def update_live_typing():
    data = request.get_json(force=True)
    chat_id = data.get("chat_id")
    live_typing[chat_id] = data.get("text", "")
    return jsonify({"status": "ok"})

@app.route("/get_live_typing/<chat_id>")
def get_live_typing(chat_id):
    return jsonify({"text": live_typing.get(chat_id, "")})

# ---------------- MARK READ ----------------
@app.route("/mark_read", methods=["POST"])
def mark_read():
    data = request.get_json(force=True)
    chat_id = data.get("chat_id")
    reader = data.get("reader")
    if not chat_id or not reader:
        return jsonify({"status": "error"}), 400

    msgs = all_chats.get(chat_id, [])
    if not msgs:
        return jsonify({"status": "ok"})

    last_msg = msgs[-1]
    if reader not in last_msg["seen_by"]:
        last_msg["seen_by"].append(reader)

    broadcast(chat_id, {
        "type": "read",
        "index": len(msgs) - 1,
        "seen_by": last_msg["seen_by"]
    })
    return jsonify({"status": "ok"})

# ---------------- LOGOUT ----------------
@app.route("/logout_user", methods=["POST"])
def logout_user():
    data = request.get_json(force=True, silent=True) or {}
    cid = data.get("chat_id", CHAT_ID)
    online_users[cid] = False
    live_typing[cid] = ""
    all_chats[cid] = []
    broadcast(cid, {"type": "cleared"})
    return jsonify({"status": "ok"})

@app.route("/logout_agent", methods=["POST"])
def logout_agent():
    online_users["agent"] = False
    return jsonify({"status": "ok"})

# ---------------- SSE EVENTS ----------------
@app.route("/events/<chat_id>")
def events(chat_id):
    q = queue.Queue()
    sse_subscribers.setdefault(chat_id, []).append(q)

    def stream():
        try:
            while True:
                try:
                    data = q.get(timeout=15)
                    yield f"data: {data}\n\n"
                except queue.Empty:
                    yield "data: {}\n\n"  # heartbeat every 15s
        except GeneratorExit:
            pass
        finally:
            sse_subscribers.get(chat_id, []).remove(q)

    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "text/event-stream",
        "X-Accel-Buffering": "no"
    }
    return Response(stream_with_context(stream()), headers=headers)

# ---------------- MAIN ----------------
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, threaded=True)
