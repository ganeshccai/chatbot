from flask import Flask, request, jsonify
from flask_cors import CORS
from google.cloud import firestore

try:
    from google.cloud import dialogflowcx_v3 as dialogflow
except ImportError as e:
    print(
        "ERROR: Could not import dialogflowcx_v3. Try running: pip install google-cloud-dialogflow-cx==0.6.0"
    )
    raise
from google.api_core.exceptions import GoogleAPICallError
import os
import uuid
import logging
import time

# Configure logging to show timestamps and level
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__)

# Print startup message
print("=" * 50)
print("Starting CCAI Chat Server...")
print("=" * 50)

# Allow browser-based agent UI to call endpoints (adjust origins in production)
CORS(app, resources={r"/*": {"origins": "*"}})


# ================== HEALTH ENDPOINT ==================
@app.route("/health", methods=["GET"])
def health():
    result = {"firestore": False, "dialogflow": False}
    # Firestore check
    try:
        # Try listing collections (should not fail if Firestore is up)
        _ = list(db.collections())
        result["firestore"] = True
    except Exception as e:
        logging.exception("Firestore health check failed: %s", e)
    # Dialogflow CX check
    try:
        client_options = {"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
        client = dialogflow.SessionsClient(client_options=client_options)
        # Just create client, don't send request
        result["dialogflow"] = True
    except Exception as e:
        logging.exception("Dialogflow CX health check failed: %s", e)
    return jsonify(result), 200


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

    start_time = time.time()
    data = request.get_json(silent=True, force=True) or {}
    logging.info("📩 Webhook received: %s", data)

    # Add timeout check
    def check_timeout():
        # Dialogflow has 30s timeout, we'll respond by 25s
        if time.time() - start_time > 25:
            logging.warning("Webhook approaching timeout, returning early")
            return True
        return False

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
    try:
        cx_reply = send_to_cx(session_id, text_input, timeout_check=check_timeout)

        # Check timeout before saving to Firestore
        if not check_timeout():
            # Save agent reply to Firestore (if any)
            if cx_reply:
                save_message(session_id, "agent", cx_reply)
        else:
            cx_reply = "Sorry, the request is taking too long. Please try again."
    except Exception as e:
        logging.exception("Error while sending to Dialogflow CX: %s", e)
        cx_reply = "An error occurred. Please try again."

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


def send_to_cx(session_id, message, timeout_check=None):
    """Send message to Dialogflow CX and return agent text reply"""
    if not message:
        logging.info("No message provided to send_to_cx for session %s", session_id)
        return ""

    # Check for timeout before making external call
    if timeout_check and timeout_check():
        return "Sorry, the request is taking too long. Please try again."

    client_options = {
        "api_endpoint": f"{LOCATION}-dialogflow.googleapis.com",
        # Set shorter timeout for API calls
        "timeout": 20,
    }
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
    port = int(os.environ.get("PORT", 8080))
    print(f"\nServer starting on http://localhost:{port}")
    print("You can test the server with:")
    print(f"  Health check: http://localhost:{port}/health")
    print(f"  Webhook test: Use PowerShell to run:")
    print(
        '    $body = @{"session"="test-session"; "queryInput"=@{"text"=@{"text"="hello"}}} | ConvertTo-Json'
    )
    print(
        f'    Invoke-RestMethod -Method Post -Uri http://localhost:{port}/webhook -ContentType "application/json" -Body $body'
    )
    print("\nPress Ctrl+C to stop the server")
    print("=" * 50)

    try:
        app.run(host="0.0.0.0", port=port, debug=True)
    except Exception as e:
        print(f"\nERROR: Failed to start server: {e}")
        logging.exception("Server startup failed")
        raise
