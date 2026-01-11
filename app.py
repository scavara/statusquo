import os
import logging
import random
import json
import uuid
import boto3
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_bolt.oauth.oauth_settings import OAuthSettings
from slack_sdk.oauth.state_store import FileOAuthStateStore
from boto3.dynamodb.conditions import Key # Needed for GSI Query

# --- LOCAL IMPORTS ---
from lib.installation_store import DynamoDBInstallationStore
from lib.filter_store import FilterStore

# --- CONFIGURATION ---
SLACK_CLIENT_ID = os.environ["SLACK_CLIENT_ID"]
SLACK_CLIENT_SECRET = os.environ["SLACK_CLIENT_SECRET"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

SCOPES = ["commands", "chat:write"]
USER_SCOPES = ["users.profile:write"]

# --- AWS SETUP ---
dynamodb = boto3.resource('dynamodb')
quotes_table = dynamodb.Table('FunQuotes')

# --- STORES ---
installation_store = DynamoDBInstallationStore(client_id=SLACK_CLIENT_ID)
filter_store = FilterStore()

# --- APP INIT ---
oauth_settings = OAuthSettings(
    client_id=SLACK_CLIENT_ID,
    client_secret=SLACK_CLIENT_SECRET,
    scopes=SCOPES,
    user_scopes=USER_SCOPES,
    installation_store=installation_store,
    state_store=FileOAuthStateStore(expiration_seconds=600, base_dir="./data")
)

app = App(
    signing_secret=SLACK_SIGNING_SECRET,
    oauth_settings=oauth_settings
)
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# --- COMMAND ROUTER ---
@app.command("/quo")
def handle_command(ack, body, respond):
    ack()
    full_text = body.get('text', '').strip()
    user_id = body['user_id']

    # 1. FILTER COMMANDS
    if full_text.lower().startswith("filter"):
        args = full_text.split(maxsplit=1) # Split into "filter" and "Rest of string"
        
        if len(args) < 2:
             respond("⚠️ Usage: `/quo filter <Author Name>`, `/quo filter list`, or `/quo filter flush`")
             return

        sub_action = args[1].strip()

        # FLUSH
        if sub_action.lower() == "flush":
            filter_store.clear_filter(user_id)
            respond("🗑️ Filter cleared! You will now receive random quotes.")
            return
        
        # LIST
        if sub_action.lower() == "list":
            current = filter_store.get_filter(user_id)
            msg = f"🔍 Current filter: *{current}*" if current else "No filter active (Random mode)."
            respond(msg)
            return

        # SET FILTER (Proactive Validation)
        author_name = sub_action.replace('"', '').replace("'", "") # Clean quotes
        
        # Check if we actually have quotes for this author using the GSI
        response = quotes_table.query(
            IndexName='AuthorIndex',
            KeyConditionExpression=Key('author').eq(author_name)
        )
        
        if response['Count'] == 0:
            respond(f"⚠️ I couldn't find any quotes by *{author_name}* yet. Filter NOT set.\nTry adding one first: `/quo add ...`")
        else:
            filter_store.set_filter(user_id, author_name)
            respond(f"✅ Filter set! Next update will only show quotes from: *{author_name}*")
        return

    # 2. ADD COMMAND
    if full_text.lower().startswith("add"):
        payload = full_text[3:].strip()
        handle_add_quote(payload, body, respond)
        return

    # 3. MANUAL UPDATE (Triggered via helper script if needed, or just warn user)
    if not full_text:
        respond("ℹ️ Global updates run automatically at 9:00 AM daily based on your preferences.")
        return

    respond("⚠️ Unknown subcommand. Try `/quo filter <name>` or `/quo add ...`")

def handle_add_quote(user_input, body, respond):
    # ... (Keep your existing handle_add_quote logic exactly as is) ...
    # Just copying the simplified version here for brevity
    parts = user_input.split("|")
    if len(parts) != 3:
        respond(text="⚠️ Format: `/quo add Text | Author | :emoji:`")
        return
    # ... (rest of logic) ...
    
    # ... (Ensure your existing ACTION handlers for approve/deny are still here) ...
    # They are omitted here for brevity but DO NOT DELETE THEM from your file.

# --- FLASK ROUTES ---
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)

@flask_app.route("/slack/install", methods=["GET"])
def slack_install():
    return handler.handle(request)

@flask_app.route("/slack/oauth_redirect", methods=["GET"])
def slack_oauth_redirect():
    return handler.handle(request)

if __name__ == "__main__":
    # Note: Scheduler is GONE from here.
    port = int(os.environ.get("PORT", 3000))
    print(f"⚡️ StatusQuo Web Server running on port {port}!")
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
