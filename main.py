from flask import Flask, request, jsonify
from flask_cors import CORS
from google.cloud import firestore
from google.cloud import dialogflowcx_v3 as dialogflow
from google.api_core.exceptions import GoogleAPICallError
import os
import uuid
import logging

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
# Allow browser-based agent UI to call endpoints (adjust origins in production)
CORS(app, resources={r"/*": {"origins": "*"}})

# ================== CONFIG ==================
try:
    db = firestore.Client()
except Exception as e:
    logging.exception("Failed to initialize Firestore client: %s", e)
    db = None

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "project001-474715")
LOCATION = os.getenv("LOCATION", "us-central1")
AGENT_ID = os.getenv("AGENT_ID", "f82d4b5f-ee2f-402c-8aa6-cb11b0a8e56d")


# ================== USER SIDE (Webhook) ==================
@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return "Webhook active", 200

    data = request.get_json(silent=True, force=True) or {}
    logging.info("📩 Webhook received: %s", data)

    # Extract session id safely
    # Try several possible locations for session id used by Dialogflow CX
    session_path = (
        data.get("session")
        or data.get("sessionInfo", {}).get("session")
        or data.get("originalDetectIntentRequest", {}).get("payload", {}).get("session")
        or ""
    )
    if session_path:
        session_id = session_path.split("/")[-1]
    else:
        # Fallback to generated id to avoid collisions; in production prefer client-provided session id
        session_id = f"session-{uuid.uuid4().hex}"

    logging.info("Using session_id=%s", session_id)

    # Extract user message safely
    # Extract user message from common Dialogflow CX webhook payload shapes
    text_input = ""
    try:
        # direct text field
        if isinstance(data.get("text"), str) and data.get("text").strip():
            text_input = data.get("text").strip()
        # queryInput.text.text (from df-messenger)
        elif data.get("queryInput") and data["queryInput"].get("text"):
            # queryInput.text may be either a string or an object with 'text'
            qi_text = data["queryInput"]["text"]
            if isinstance(qi_text, dict):
                text_input = qi_text.get("text", "") or qi_text.get("text", "")
            elif isinstance(qi_text, str):
                text_input = qi_text
        # queryResult.text (older/alternate payloads)
        elif data.get("queryResult") and data["queryResult"].get("text"):
            text_input = data["queryResult"]["text"]
        else:
            text_input = ""
    except Exception:
        logging.exception("Error extracting text from webhook payload")
        text_input = ""

    if not text_input:
        logging.info("No text found in payload; setting text_input to empty string")

    # Save user message
    saved = save_message(session_id, "user", text_input)
    if not saved:
        logging.warning("Failed to save user message for session %s", session_id)

    # Get Dialogflow CX agent reply
    # Get Dialogflow CX agent reply
    try:
        cx_reply = send_to_cx(session_id, text_input)

        # Save agent reply to Firestore (if any)
        if cx_reply:
            save_message(session_id, "agent", cx_reply)
    except Exception as e:
        logging.exception("Error while sending to Dialogflow CX: %s", e)
        cx_reply = ""

    # Respond back to Dialogflow or user
    # Respond back to Dialogflow with the agent text (if available)
    return (
        jsonify(
            {"fulfillment_response": {"messages": [{"text": {"text": [cx_reply]}}]}}
        ),
        200,
    )


# ================== AGENT SIDE (Manual Reply) ==================
@app.route("/agent-reply", methods=["POST"])
def agent_reply():
    data = request.get_json()
    session_id = data.get("session")
    message = data.get("message")

    if not session_id or not message:
        return jsonify({"error": "session and message are required"}), 400

    # Save to Firestore
    saved = save_message(session_id, "agent", message)
    if not saved:
        return jsonify({"error": "failed to save message to Firestore"}), 500

    # Send to Dialogflow CX (so CX can continue the flow)
    try:
        send_to_cx(session_id, message)
        return jsonify({"status": "Agent reply sent to CX"}), 200
    except Exception as e:
        logging.exception("Error sending agent reply to CX: %s", e)
        return jsonify({"error": str(e)}), 500


# ================== HELPERS ==================
def save_message(session_id, sender, message):
    """Store messages under sessions/{session_id}/messages"""
    if db is None:
        logging.error("Firestore client is not initialized; cannot save message")
        return False

    try:
        session_ref = db.collection("sessions").document(session_id)
        msg_ref = session_ref.collection("messages").document()

        msg_ref.set(
            {
                "sender": sender,
                "message": message,
                "timestamp": firestore.SERVER_TIMESTAMP,
            }
        )

        # Update session info
        session_ref.set(
            {"last_sender": sender, "updated_at": firestore.SERVER_TIMESTAMP},
            merge=True,
        )
        return True
    except GoogleAPICallError as e:
        logging.exception("Firestore API error when saving message: %s", e)
        return False
    except Exception as e:
        logging.exception("Unexpected error when saving message: %s", e)
        return False


def send_to_cx(session_id, message):
    """Send message to Dialogflow CX and return agent text reply"""
    if not message:
        logging.info("No message provided to send_to_cx for session %s", session_id)
        return ""

    client_options = {"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    try:
        client = dialogflow.SessionsClient(client_options=client_options)
        session_path = f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/{AGENT_ID}/sessions/{session_id}"

        text_input = dialogflow.TextInput(text=message)
        query_input = dialogflow.QueryInput(text=text_input, language_code="en")

        response = client.detect_intent(
            request={"session": session_path, "query_input": query_input}
        )

        logging.info("Sent to CX: %s", message)
        logging.info(
            "CX Response messages: %s", response.query_result.response_messages
        )

        # Extract text replies (if any)
        messages = []
        for msg in response.query_result.response_messages:
            if getattr(msg, "text", None) and getattr(msg.text, "text", None):
                messages.extend(msg.text.text)

        return " ".join(messages) if messages else ""
    except Exception as e:
        logging.exception("Dialogflow CX request failed: %s", e)
        raise


# ================== MAIN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
