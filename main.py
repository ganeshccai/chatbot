from flask import Flask, render_template, request, session, jsonify, Response, stream_with_context
from flask_cors import CORS
import queue
import json
import time

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = "temp_key"
CORS(app)

CHAT_ID = "1234"
CHAT_PASSWORD = "1"

# ---------------- In-memory stores ----------------
all_chats = {}          # chat_id -> list of messages
online_users = {}       # chat_id -> True/False
live_typing = {}        # chat_id -> text
sse_subscribers = {}    # chat_id -> list of Queues

# ---------------- User Page ----------------
@app.route("/user", methods=["GET","POST"])
def user_page():
    if request.method=="POST":
        password=request.form.get("password")
        if password==CHAT_PASSWORD:
            session["chat_id"]=CHAT_ID
            all_chats[CHAT_ID] = []          # clear chat on login
            online_users[CHAT_ID]=True
            live_typing[CHAT_ID] = ""
            return render_template("user.html")
        return "Wrong password"
    return """<form method="post"><input type="password" name="password"/><input type="submit"/></form>"""

# ---------------- Agent Page ----------------
@app.route("/agent", methods=["GET","POST"])
def agent_page():
    if request.method=="POST":
        password=request.form.get("password")
        if password==CHAT_PASSWORD:
            online_users["agent"]=True
            return render_template("agent.html")
        return "Wrong password"
    return """<form method="post"><input type="password" name="password"/><input type="submit"/></form>"""

# ---------------- Send Message ----------------
@app.route("/send", methods=["POST"])
def send_message():
    data = request.get_json()
    chat_id = data.get("chat_id")
    sender = data.get("sender")
    text = data.get("text","").strip()
    if not chat_id or not sender or not text:
        return jsonify({"status":"error","message":"chat_id, sender, text required"}),400

    msg = {"sender":sender,"text":text,"seen_by":[]}
    all_chats.setdefault(chat_id,[]).append(msg)

    # SSE broadcast instantly
    for q in sse_subscribers.get(chat_id,[]):
        try:
            q.put_nowait(json.dumps({"type":"new_message","message":msg,"chat_id":chat_id}))
        except Exception: pass

    return jsonify({"status":"ok"})

# ---------------- Get Messages ----------------
@app.route("/messages/<chat_id>")
def get_messages(chat_id):
    return jsonify(all_chats.get(chat_id, []))

# ---------------- Online Status ----------------
@app.route("/is_online/<chat_id>")
def is_online(chat_id):
    return jsonify({"user_online": online_users.get(chat_id,False),"online":online_users.get("agent",False)})

# ---------------- Live Typing ----------------
@app.route("/live_typing", methods=["POST"])
def update_live_typing():
    data=request.get_json()
    chat_id=data.get("chat_id")
    live_typing[chat_id]=data.get("text","").strip()
    return jsonify({"status":"ok"})

@app.route("/get_live_typing/<chat_id>")
def get_live_typing(chat_id):
    return jsonify({"text": live_typing.get(chat_id,"")})

# ---------------- Logout ----------------
@app.route("/logout_user", methods=["POST"])
def logout_user():
    data=request.get_json(force=True,silent=True) or {}
    chat_id=data.get("chat_id", CHAT_ID)
    online_users[chat_id]=False
    live_typing[chat_id]=""
    return jsonify({"status":"ok"})

@app.route("/logout_agent", methods=["POST"])
def logout_agent():
    online_users["agent"]=False
    return jsonify({"status":"ok"})

# ---------------- Mark Read ----------------
@app.route("/mark_read", methods=["POST"])
def mark_read():
    data=request.get_json(force=True,silent=True) or {}
    chat_id=data.get("chat_id")
    reader=data.get("reader")
    if not chat_id or not reader:
        return jsonify({"status":"error","message":"chat_id and reader required"}),400

    msgs=all_chats.get(chat_id,[])
    if not msgs: return jsonify({"status":"error","message":"no messages"}),404

    last_msg=msgs[-1]
    if reader not in last_msg.get("seen_by",[]):
        last_msg.setdefault("seen_by",[]).append(reader)

    # SSE notify read instantly
    payload=json.dumps({"type":"read","index":len(msgs)-1,"seen_by":last_msg["seen_by"],"chat_id":chat_id})
    for q in sse_subscribers.get(chat_id,[]):
        try: q.put_nowait(payload)
        except Exception: pass

    return jsonify({"status":"ok","seen_by":last_msg["seen_by"]})

# ---------------- SSE Events ----------------
@app.route("/events/<chat_id>")
def events(chat_id):
    q=queue.Queue()
    sse_subscribers.setdefault(chat_id,[]).append(q)

    def gen():
        try:
            while True:
                data=q.get()
                if data is None: break
                yield f"data: {data}\n\n"
        except GeneratorExit: pass
        finally:
            try: sse_subscribers.get(chat_id,[]).remove(q)
            except Exception: pass

    return Response(stream_with_context(gen()), mimetype="text/event-stream")

if __name__=="__main__":
    import os
    port=int(os.environ.get("PORT",8080))
    app.run(host="0.0.0.0", port=port, threaded=True)
