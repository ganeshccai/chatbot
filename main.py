from flask import Flask, render_template, request, jsonify, Response, session, stream_with_context
from flask_cors import CORS
import json, queue

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = "temp_key"
CORS(app)

CHAT_ID = "1234"
CHAT_PASSWORD = "1"

# memory stores
all_chats = {}
online_users = {}
live_typing = {}
sse_subscribers = {}

# ---------------- USER ----------------
@app.route("/user", methods=["GET", "POST"])
def user_page():
    if request.method == "POST":
        password = request.form.get("password")
        if password == CHAT_PASSWORD:
            session["chat_id"] = CHAT_ID
            # clear chat on login
            all_chats[CHAT_ID] = []
            live_typing[CHAT_ID] = ""
            online_users[CHAT_ID] = True
            return render_template("user.html")
        return "Wrong password"
    return """<form method="post">
                <input type="password" name="password" placeholder="*****"/>
                <input type="submit" value="Login"/>
              </form>"""

# ---------------- AGENT ----------------
@app.route("/agent", methods=["GET", "POST"])
def agent_page():
    if request.method == "POST":
        password = request.form.get("password")
        if password == CHAT_PASSWORD:
            online_users["agent"] = True
            return render_template("agent.html")
        return "Wrong password"
    return """<form method="post">
                <input type="password" name="password" placeholder="*****"/>
                <input type="submit" value="Login"/>
              </form>"""

# ---------------- SEND MESSAGE ----------------
@app.route("/send", methods=["POST"])
def send_message():
    data = request.get_json(force=True)
    chat_id = data.get("chat_id")
    sender = data.get("sender")
    text = data.get("text", "").strip()

    if not chat_id or not sender or not text:
        return jsonify({"status": "error", "message": "Missing data"}), 400

    msg = {"sender": sender, "text": text, "seen_by": []}
    all_chats.setdefault(chat_id, []).append(msg)

    # broadcast via SSE
    payload = json.dumps({"type": "new_message", "message": msg, "chat_id": chat_id})
    for q in sse_subscribers.get(chat_id, []):
        q.put_nowait(payload)

    return jsonify({"status": "ok"})

# ---------------- MARK READ ----------------
@app.route("/mark_read", methods=["POST"])
def mark_read():
    data = request.get_json(force=True)
    chat_id = data.get("chat_id")
    reader = data.get("reader")

    if not chat_id or not reader:
        return jsonify({"status": "error", "message": "Missing info"}), 400

    msgs = all_chats.get(chat_id, [])
    if not msgs:
        return jsonify({"status": "ok"})

    last_msg = msgs[-1]
    if reader not in last_msg["seen_by"]:
        last_msg["seen_by"].append(reader)

    payload = json.dumps({
        "type": "read",
        "index": len(msgs) - 1,
        "seen_by": last_msg["seen_by"],
        "chat_id": chat_id
    })
    for q in sse_subscribers.get(chat_id, []):
        q.put_nowait(payload)

    return jsonify({"status": "ok"})

# ---------------- ONLINE STATUS ----------------
@app.route("/is_online/<chat_id>")
def is_online(chat_id):
    return jsonify({
        "user_online": online_users.get(chat_id, False),
        "online": online_users.get("agent", False)
    })

# ---------------- LIVE TYPING ----------------
@app.route("/live_typing", methods=["POST"])
def live_typing_update():
    data = request.get_json(force=True)
    chat_id = data.get("chat_id")
    text = data.get("text", "")
    live_typing[chat_id] = text
    return jsonify({"status": "ok"})

@app.route("/get_live_typing/<chat_id>")
def get_live_typing(chat_id):
    return jsonify({"text": live_typing.get(chat_id, "")})

# ---------------- LOGOUT ----------------
@app.route("/logout_user", methods=["POST"])
def logout_user():
    data = request.get_json(force=True, silent=True) or {}
    chat_id = data.get("chat_id", CHAT_ID)
    online_users[chat_id] = False
    live_typing[chat_id] = ""
    all_chats[chat_id] = []
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
                msg = q.get()
                if msg is None:
                    break
                yield f"data: {msg}\n\n"
        except GeneratorExit:
            pass
        finally:
            if chat_id in sse_subscribers:
                try:
                    sse_subscribers[chat_id].remove(q)
                except ValueError:
                    pass

    return Response(stream_with_context(stream()), mimetype="text/event-stream")

# ---------------- MAIN ----------------
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, threaded=True)
