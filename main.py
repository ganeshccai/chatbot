from flask import Flask, request, jsonify
from google.cloud import firestore
from google.cloud import dialogflowcx_v3 as dialogflow
import os

app = Flask(__name__)

# ================== CONFIG ==================
db = firestore.Client()

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "project001-474715")
LOCATION = os.getenv("LOCATION", "us-central1")
AGENT_ID = os.getenv("AGENT_ID", "f82d4b5f-ee2f-402c-8aa6-cb11b0a8e56d")


# ================== USER SIDE (Webhook) ==================
@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return "Webhook active", 200

    data = request.get_json(silent=True, force=True)
    print("📩 Webhook received:", data)

    # Extract session id safely
    session_path = (
        data.get("session") or data.get("sessionInfo", {}).get("session") or ""
    )
    session_id = session_path.split("/")[-1] if "/" in session_path else "test_session"

    # Extract user message safely
    text_input = ""
    try:
        if isinstance(data.get("text"), str):
            text_input = data.get("text")
        elif "queryInput" in data and "text" in data["queryInput"]:
            text_input = data["queryInput"]["text"].get("text", "")
        elif "queryResult" in data and "text" in data["queryResult"]:
            text_input = data["queryResult"]["text"]
        else:
            text_input = "no text found"
    except Exception as e:
        print("Error extracting text:", e)
        text_input = "no text found"

    # Save user message
    save_message(session_id, "user", text_input)

    # Get Dialogflow CX agent reply
    try:
        cx_reply = send_to_cx(session_id, text_input)

        # Save agent reply to Firestore
        if cx_reply:
            save_message(session_id, "agent", cx_reply)
    except Exception as e:
        print("Error while CX detect_intent:", e)
        cx_reply = "Error from CX"

    # Respond back to Dialogflow or user
    return (
        jsonify(
            {
                "fulfillment_response": {
                    "messages": [{"text": {"text": [cx_reply]}}],
                }
            }
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
    save_message(session_id, "agent", message)

    # Send to Dialogflow CX (so CX can continue the flow)
    try:
        send_to_cx(session_id, message)
        return jsonify({"status": "Agent reply sent to CX"}), 200
    except Exception as e:
        print("Error sending to CX:", e)
        return jsonify({"error": str(e)}), 500


# ================== HELPERS ==================
def save_message(session_id, sender, message):
    """Store messages under sessions/{session_id}/messages"""
    session_ref = db.collection("sessions").document(session_id)
    msg_ref = session_ref.collection("messages").document()

    msg_ref.set(
        {"sender": sender, "message": message, "timestamp": firestore.SERVER_TIMESTAMP}
    )

    # Update session info
    session_ref.set(
        {"last_sender": sender, "updated_at": firestore.SERVER_TIMESTAMP}, merge=True
    )


def send_to_cx(session_id, message):
    """Send message to Dialogflow CX and return agent text reply"""
    client_options = {"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"}
    client = dialogflow.SessionsClient(client_options=client_options)

    session_path = f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/{AGENT_ID}/sessions/{session_id}"

    text_input = dialogflow.TextInput(text=message)
    query_input = dialogflow.QueryInput(text=text_input, language_code="en")

    response = client.detect_intent(
        request={"session": session_path, "query_input": query_input}
    )

    print("Sent to CX:", message)
    print("💬 CX Response:", response.query_result.response_messages)

    # Extract text replies (if any)
    messages = []
    for msg in response.query_result.response_messages:
        if msg.text and msg.text.text:
            messages.extend(msg.text.text)

    return " ".join(messages) if messages else "CX replied but no text found."


# ================== MAIN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
