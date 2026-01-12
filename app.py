import os
import logging
import json
import uuid
import boto3
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_bolt.oauth.oauth_settings import OAuthSettings
from slack_sdk.oauth.state_store import FileOAuthStateStore
from boto3.dynamodb.conditions import Key, Attr

# --- LOCAL IMPORTS ---
# Ensure you have the 'lib' folder with these files created from previous steps
from lib.installation_store import DynamoDBInstallationStore
from lib.filter_store import FilterStore
from lib.status_logic import perform_user_update
from lib.quote_deduplicator import QuoteDeduplicator

# --- CONFIGURATION ---
SLACK_CLIENT_ID = os.environ["SLACK_CLIENT_ID"]
SLACK_CLIENT_SECRET = os.environ["SLACK_CLIENT_SECRET"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

SCOPES = ["commands", "chat:write"]
USER_SCOPES = ["users.profile:write"]

# --- AWS DYNAMODB SETUP ---
# We keep the quotes table here for command validation and adding new quotes
dynamodb = boto3.resource("dynamodb")
quotes_table = dynamodb.Table("FunQuotes")
deduplicator = QuoteDeduplicator(quotes_table)

# --- STORES ---
installation_store = DynamoDBInstallationStore(client_id=SLACK_CLIENT_ID)
filter_store = FilterStore()

# --- APP INITIALIZATION ---
oauth_settings = OAuthSettings(
    client_id=SLACK_CLIENT_ID,
    client_secret=SLACK_CLIENT_SECRET,
    scopes=SCOPES,
    user_scopes=USER_SCOPES,
    installation_store=installation_store,
    state_store=FileOAuthStateStore(expiration_seconds=600, base_dir="./data"),
)

app = App(signing_secret=SLACK_SIGNING_SECRET, oauth_settings=oauth_settings)
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)


# ==========================================
# 1. COMMAND: /quo-update
# ==========================================
@app.command("/quo-update")
def handle_update_command(ack, body, respond):
    """
    Triggers an IMMEDIATE manual update for the user.
    """
    ack()

    user_id = body["user_id"]
    team_id = body["team_id"]

    # 1. Fetch the installation to get the token
    # Note: This assumes the person running the command IS the installer.
    # If a different user runs this, we won't have their specific token unless
    # they also installed the app.
    installation = installation_store.find_installation(
        enterprise_id=body.get("enterprise_id"), team_id=team_id
    )

    if not installation:
        respond("❌ I couldn't find an installation record for this team.")
        return

    if installation.user_id != user_id:
        respond(
            f"⚠️ Permission Denied. I only have a token for <@{installation.user_id}> (the installer). only they can update their status."
        )
        return

    respond("🔄 Updating your status now...")

    # 2. Perform the update using our shared library
    success, result_msg = perform_user_update(
        installation=installation,
        client=app.client,
        filter_store=filter_store,
        quotes_table=quotes_table,
    )

    if success:
        respond(f"✅ Done! Status updated to:\n> {result_msg}")
    else:
        respond(f"❌ Update failed: {result_msg}")


# ==========================================
# 2. COMMAND: /quo-add
# ==========================================
@app.command("/quo-add")
def handle_add_command(ack, body, respond):
    """
    Handles: /quo-add "Quote" | Author | :emoji:
    """
    ack()
    user_input = body.get("text", "").strip()

    # Validation
    parts = user_input.split("|")
    if len(parts) != 3:
        respond(text="⚠️ Format required: `/quo-add Quote Text | Author Name | :emoji:`")
        return

    clean_text = parts[0].strip().strip('"').strip("'")
    clean_author = parts[1].strip()
    clean_emoji = parts[2].strip()

    # --- 1. VALIDATE EMOJI (Existing) ---
    if not (clean_emoji.startswith(":") and clean_emoji.endswith(":")):
        respond(
            f"⚠️ Invalid emoji format: `{clean_emoji}`.\nMust be a valid Slack shortcode like `:wave:` or `:robot_face:`."
        )
        return

    # --- 2. DUPLICATE CHECK (New) ---
    is_duplicate, existing_item = deduplicator.check_exists(clean_text)
    if is_duplicate:
        # Inform user and show the existing one
        exist_author = existing_item.get("author", "Unknown")
        respond(
            f"🛑 *Duplicate Quote Detected!*\n"
            f"We already have this quote in the database:\n"
            f'> "{clean_text}" -- {exist_author}\n'
            f"No need to add it again!"
        )
        return

    # Create proposal payload
    proposal_data = json.dumps(
        {
            "text": clean_text,
            "author": clean_author,
            "emoji": clean_emoji,
            "proposer": body["user_id"],
        }
    )

    # Send Approval Card
    respond(
        response_type="in_channel",
        text="New Quote Request",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*New Quote Request:*\n> {clean_emoji} \"{clean_text}\"\n> -- _{clean_author}_\n_Requested by <@{body['user_id']}>_",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": "approve_quote",
                        "value": proposal_data,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Deny"},
                        "style": "danger",
                        "action_id": "deny_quote",
                    },
                ],
            },
        ],
    )


# ==========================================
# 3. COMMAND: /quo-filter
# ==========================================
@app.command("/quo-filter")
def handle_filter_command(ack, body, respond):
    """
    Handles:
    /quo-filter Mark (matches Mark Twain, Mark Hamill, etc.)
    /quo-filter list
    /quo-filter flush
    """
    ack()
    user_input = body.get("text", "").strip()
    user_id = body["user_id"]

    if not user_input:
        respond(
            "⚠️ Usage: `/quo-filter <Author Name>`, `/quo-filter list`, or `/quo-filter flush`"
        )
        return

    # --- SUBCOMMANDS: FLUSH & LIST (Keep exactly as they were) ---
    if user_input.lower() == "flush":
        if filter_store.clear_filter(user_id):
            respond("🗑️ Filter cleared! You will now receive random quotes.")
        else:
            respond("❌ Error clearing filter.")
        return

    if user_input.lower() == "list":
        current = filter_store.get_filter(user_id)
        msg = (
            f"🔍 Current filter: *{current}*"
            if current
            else "No filter active (Random mode)."
        )
        respond(msg)
        return

    # --- SUBCOMMAND: SET FILTER (Updated for Partial Match) ---
    author_partial = user_input.replace('"', "").replace("'", "")

    try:
        # Use SCAN with CONTAINS instead of QUERY
        # We limit to 1 item because we just need to know if ANY exist
        response = quotes_table.scan(
            FilterExpression=Attr('author').contains(author_partial)
        )

        if response["Count"] == 0:
            respond(
                f"⚠️ I couldn't find any quotes matching *'{author_partial}'*.\nTry adding one first: `/quo-add ...`"
            )
        else:
            if filter_store.set_filter(user_id, author_partial):
                respond(
                    f"✅ Filter set! Matches quotes containing: *'{author_partial}'*"
                )
            else:
                respond("❌ Database error setting filter.")

    except Exception as e:
        respond(f"❌ Database error checking author: {e}")


# ==========================================
# 4. ACTIONS (INTERACTIVITY)
# ==========================================
@app.action("approve_quote")
def handle_approval(ack, body, respond):
    ack()
    action_value = body["actions"][0]["value"]
    data = json.loads(action_value)
    quote_id = str(uuid.uuid4())

    try:
        quotes_table.put_item(
            Item={
                "quote_id": quote_id,
                "text": data["text"],
                "author": data["author"],
                "emoji": data["emoji"],
            }
        )
        respond(
            text="Quote Approved!",
            replace_original=True,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"✅ *Approved by <@{body['user']['id']}>*\n> {data['emoji']} \"{data['text']}\" --{data['author']}",
                    },
                }
            ],
        )
    except Exception as e:
        respond(text=f"❌ Error saving quote: {e}")


@app.action("deny_quote")
def handle_denial(ack, body, respond):
    ack()
    respond(
        text="Quote Denied",
        replace_original=True,
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"❌ *Denied by <@{body['user']['id']}>*",
                },
            }
        ],
    )


# ==========================================
# 5. FLASK ROUTES
# ==========================================
@flask_app.route("/", methods=["GET"])
def index():
    return "⚡️ StatusQuo Bot is running! <br><br><a href='/slack/install'>Click here to Add to Slack</a>"


@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    return handler.handle(request)


@flask_app.route("/slack/install", methods=["GET"])
def slack_install():
    return handler.handle(request)


@flask_app.route("/slack/oauth_redirect", methods=["GET"])
def slack_oauth_redirect():
    return handler.handle(request)


# ==========================================
# 6. RUNNER
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    print(f"⚡️ StatusQuo Web Server running on port {port}!")
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
