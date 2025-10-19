from flask import Flask, request, jsonify
from google.cloud import firestore
import os

app = Flask(__name__)

# Initialize Firestore (Firebase) client
# Make sure Firestore is enabled in the same GCP project
db = firestore.Client()


@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return "Webhook active", 200

    data = request.get_json(silent=True, force=True)
    print("🔍 Webhook received:", data)

    # Safe session id
    session_path = (
        data.get("session")
        or data.get("sessionInfo", {}).get("session")
        or ""
    )
    session_id = session_path.split("/")[-1] if "/" in session_path else "test_session"

    # Safe text extraction
    text_input = ""
    try:
        if isinstance(data.get("text"), str):
            text_input = data.get("text")
        elif isinstance(data.get("text"), dict):
            text_input = data.get("text", {}).get("text", [""])[0]
        elif isinstance(data.get("queryResult"), dict):
            text_input = data.get("queryResult", {}).get("text", "")
        elif isinstance(data.get("queryInput"), dict):
            text_input = data.get("queryInput", {}).get("text", {}).get("text", "")
        else:
            text_input = "no text found"
    except Exception as e:
        print("❌ Error extracting text safely:", e)
        text_input = "no text found"

    if not text_input:
        text_input = "no text found"

    save_message(session_id, "user", text_input)

    return jsonify({
        "fulfillment_response": {
            "messages": [
                {"text": {"text": ["✅ Message received by Agent Webhook"]}}
            ]
        }
    }), 200


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
