from flask import Flask, request, jsonify
from google.cloud import firestore
import os

app = Flask(__name__)

# Initialize Firestore (Firebase) client
# Make sure Firestore is enabled in the same GCP project
db = firestore.Client()

@app.route("/", methods=["GET"])
def home():
    return "Chat Agent Webhook running!", 200


# 1️⃣ User messages from Dialogflow webhook
@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive messages from Dialogflow CX and save to Firestore"""
    data = request.get_json(silent=True, force=True)

    # Extract session id (last part of the session path)
    session_path = data.get("session", "")
    session_id = session_path.split("/")[-1] if session_path else "unknown_session"

    # Try to extract message text
    text_input = ""
    try:
        text_input = data["text"]
    except:
        try:
            text_input = data["queryResult"]["text"]
        except:
            text_input = "no text found"

    # Save user's message
    save_message(session_id, "user", text_input)

    # Respond to Dialogflow (no AI, just ack)
    return jsonify({
        "fulfillment_response": {
            "messages": [
                {"text": {"text": ["✅ Message received by Agent Webhook"]}}
            ]
        }
    })


# 2️⃣ Agent manual reply (can be called from your custom UI)
@app.route("/agent-reply", methods=["POST"])
def agent_reply():
    """Agent manually sends a message"""
    data = request.get_json()
    session_id = data.get("session")
    message = data.get("message")

    if not session_id or not message:
        return jsonify({"error": "session and message are required"}), 400

    save_message(session_id, "agent", message)
    return jsonify({"status": "saved"}), 200


# Helper: Save messages in Firestore
def save_message(session_id, sender, message):
    """Store messages under sessions/{session_id}/messages"""
    session_ref = db.collection("sessions").document(session_id)
    msg_ref = session_ref.collection("messages").document()

    msg_ref.set({
        "sender": sender,
        "message": message,
        "timestamp": firestore.SERVER_TIMESTAMP
    })

    # update session info (optional)
    session_ref.set({
        "last_sender": sender,
        "updated_at": firestore.SERVER_TIMESTAMP
    }, merge=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
