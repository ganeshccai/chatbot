from flask import Flask, request, jsonify
from google.cloud import firestore
from google.cloud import dialogflowcx_v3 as dialogflow
import os

app = Flask(__name__)

# 🔹 Firestore init
db = firestore.Client()

# 🔹 Dialogflow CX setup
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "project001-474715")
LOCATION = os.getenv("LOCATION", "us-central1")
AGENT_ID = os.getenv("AGENT_ID", "<YOUR_AGENT_ID_HERE>")


# =============== USER SIDE (Webhook) ===============
@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return "Webhook active", 200

    data = request.get_json(silent=True, force=True)
    print("🔍 Webhook received:", data)

    # Get session id
    session_path = (
        data.get("session") or data.get("sessionInfo", {}).get("session") or ""
    )
    session_id = session_path.split("/")[-1] if "/" in session_path else "test_session"

    # Extract user message safely
    text_input = ""
    try:
        if isinstance(data.get("text"), str):
            text_input = data.get("text")
        elif isinstance(data.get("queryInput"), dict):
            text_input = data["queryInput"]["text"]["text"]
        elif isinstance(data.get("queryResult"), dict):
            text_input = data["queryResult"]["text"]
        else:
            text_input = "no text found"
    except Exception as e:
        print("❌ Error extracting text:", e)
        text_input = "no text found"

    save_message(session_id, "user", text_input)

    return (
        jsonify(
            {
                "fulfillment_response": {
                    "messages": [
                        {"text": {"text": ["✅ Message received by Agent Webhook"]}}
                    ]
                }
            }
        ),
        200,
    )


# =============== AGENT SIDE (Manual Reply) ===============
@app.route("/agent-reply", methods=["POST"])
def agent_reply():
    data = request.get_json()
    session_id = data.get("session")
    message = data.get("message")

    if not session_id or not message:
        return jsonify({"error": "session and message are required"}), 400

    # Save to Firestore
    save_message(session_id, "agent", message)

    # Also send back to Dialogflow CX console
    try:
        send_to_cx(session_id, message)
        return jsonify({"status": "sent to CX and saved"}), 200
    except Exception as e:
        print("❌ Error sending to CX:", e)
        return jsonify({"error": str(e)}), 500


# =============== Helper Functions ===============
def save_message(session_id, sender, message):
    """Save messages under sessions/{session_id}/messages"""
    session_ref = db.collection("sessions").document(session_id)
    msg_ref = session_ref.collection("messages").document()
    msg_ref.set(
        {"sender": sender, "message": message, "timestamp": firestore.SERVER_TIMESTAMP}
    )
    session_ref.set(
        {"last_sender": sender, "updated_at": firestore.SERVER_TIMESTAMP}, merge=True
    )


def send_to_cx(session_id, message):
    """Send message back to Dialogflow CX"""
    client = dialogflow.SessionsClient()
    session = f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/{AGENT_ID}/sessions/{session_id}"

    text_input = dialogflow.TextInput(text=message)
    query_input = dialogflow.QueryInput(text=text_input, language_code="en")

    request = dialogflow.DetectIntentRequest(session=session, query_input=query_input)

    response = client.detect_intent(request=request)
    print("📩 Sent to CX:", response.query_result.response_messages)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
