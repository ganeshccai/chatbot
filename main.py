from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import json, threading, time

app = Flask(__name__)
CORS(app)

# store chat messages and active client connections
all_chats = {}       # {chat_id: [ {sender,text,seen_by}, ... ]}
clients = {}         # {chat_id: [Condition objects for SSE clients]}

# ------------------------------
# Utility: Broadcast message to all clients in a chat
# ------------------------------
def broadcast(chat_id, message):
    for cond in clients.get(chat_id, []):
        with cond:
            cond.msg = message
            cond.notify()


# ------------------------------
# API: Send message
# ------------------------------
@app.route("/send", methods=["POST"])
def send_message():
    data = request.json
    chat_id = data["chat_id"]
    msg = {"sender": data["sender"], "text": data["text"], "seen_by": []}
    all_chats.setdefault(chat_id, []).append(msg)
    broadcast(chat_id, {"type": "new_message", "message": msg})
    return jsonify({"status": "ok"})


# ------------------------------
# API: Typing indicator
# ------------------------------
@app.route("/typing", methods=["POST"])
def typing():
    data = request.json
    chat_id = data["chat_id"]
    sender = data["sender"]
    broadcast(chat_id, {"type": "typing", "sender": sender})
    return jsonify({"status": "ok"})


# ------------------------------
# API: Mark message as read
# ------------------------------
@app.route("/read", methods=["POST"])
def mark_read():
    data = request.json
    chat_id = data["chat_id"]
    reader = data["reader"]

    if chat_id in all_chats:
        for msg in all_chats[chat_id]:
            if reader not in msg["seen_by"]:
                msg["seen_by"].append(reader)

    broadcast(chat_id, {"type": "read", "seen_by": [reader]})
    return jsonify({"status": "ok"})


# ------------------------------
# API: Event Stream (SSE)
# ------------------------------
@app.route("/events/<chat_id>")
def events(chat_id):
    def stream():
        cond = threading.Condition()
        clients.setdefault(chat_id, []).append(cond)
        try:
            while True:
                with cond:
                    cond.wait()
                    if hasattr(cond, "msg"):
                        yield f"data: {json.dumps(cond.msg)}\n\n"
                        cond.msg = None
        except GeneratorExit:
            clients[chat_id].remove(cond)

    return Response(stream(), mimetype="text/event-stream")


# ------------------------------
# API: Check if agent online
# ------------------------------
@app.route("/is_online/<chat_id>")
def is_online(chat_id):
    online = chat_id in clients and len(clients[chat_id]) > 1
    return jsonify({"online": online})


# ------------------------------
# API: Reset chat (to clear history on refresh)
# ------------------------------
@app.route("/reset/<chat_id>", methods=["POST"])
def reset_chat(chat_id):
    all_chats[chat_id] = []
    return jsonify({"status": "cleared"})


# ------------------------------
# Root Test
# ------------------------------
@app.route("/")
def home():
    return "💬 Chat server running..."


# ------------------------------
# Run
# ------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
