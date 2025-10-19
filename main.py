from flask import Flask, request, jsonify
from google.cloud import firestore, dialogflowcx_v3 as dialogflow
import os

app = Flask(__name__)

# Initialize Firestore client
db = firestore.Client()

# Your Dialogflow CX details
PROJECT_ID = "project001-474715"
LOCATION = "us-central1"
AGENT_ID = "f82d4b5f-ee2f-402c-8aa6-cb11b0a8e56d"  # Replace with your CX Agent ID
LANGUAGE_CODE = "en"


@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return "Webhook active", 200

    data = request.get_json(silent=True, force=True)
    print("🔍 Webhook received:", data)

    # Safe session id
    session_path = (
        data.get("session") or data.get("sessionInfo", {}).get("session") or ""
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
        print("Error extracting text safely:", e)
        text_input = "no text found"

    if not text_input:
        text_input = "no text found"

    # Save user's message
    save_message(session_id, "user", text_input)

    return (
        jsonify(
            {
                "fulfillment_response": {
                    "messages": [
                        {"text": {"text": ["Message received by Agent Webhook"]}}
                    ]
                }
            }
        ),
        200,
    )


# Agent manual reply (saves to Firestore + sends to CX)
@app.route("/agent-reply", methods=["POST"])
def agent_reply():
    data = request.get_json()
    session_id = data.get("session")
    message = data.get("message")

    if not session_id or not message:
        return jsonify({"error": "session and message are required"}), 400

    # Save to Firestore
    save_message(session_id, "agent", message)

    # Send back to Dialogflow CX console
    send_to_cx(session_id, message)

    return jsonify({"status": "sent to CX and saved"}), 200


# Helper: Send message back to CX session
def send_to_cx(session_id, message):
    try:
        client = dialogflow.SessionsClient()
        session = f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/{AGENT_ID}/sessions/{session_id}"

        text_input = dialogflow.TextInput(text=message)
        query_input = dialogflow.QueryInput(
            text=text_input, language_code=LANGUAGE_CODE
        )

        response = client.detect_intent(session=session, query_input=query_input)
        print(f"Sent message to CX session: {session}")
        return response
    except Exception as e:
        print("Error sending to Dialogflow CX:", e)


# Helper: Save messages in Firestore
def save_message(session_id, sender, message):
    session_ref = db.collection("sessions").document(session_id)
    msg_ref = session_ref.collection("messages").document()

    msg_ref.set(
        {"sender": sender, "message": message, "timestamp": firestore.SERVER_TIMESTAMP}
    )

    session_ref.set(
        {"last_sender": sender, "updated_at": firestore.SERVER_TIMESTAMP}, merge=True
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
