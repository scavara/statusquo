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
from slack_sdk.errors import SlackApiError
from boto3.dynamodb.conditions import Key, Attr

# --- LOCAL IMPORTS ---
from lib.installation_store import DynamoDBInstallationStore
from lib.filter_store import FilterStore
from lib.status_logic import perform_user_update
from lib.quote_deduplicator import QuoteDeduplicator
from lib.legal_pages import PRIVACY_HTML, SUPPORT_HTML, INDEX_HTML
from lib.rate_limiter import RateLimiter

# --- CONFIGURATION ---
SLACK_CLIENT_ID = os.environ["SLACK_CLIENT_ID"]
SLACK_CLIENT_SECRET = os.environ["SLACK_CLIENT_SECRET"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

SCOPES = ["commands", "chat:write"]
USER_SCOPES = ["users.profile:write"]

# --- AWS DYNAMODB SETUP ---
dynamodb = boto3.resource("dynamodb")
quotes_table = dynamodb.Table("FunQuotes")
deduplicator = QuoteDeduplicator(quotes_table)
limiter = RateLimiter(quotes_table)

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
# 1. APP HOME TAB (VISUAL INTERFACE)
# ==========================================


def get_home_view(user_id):
    """Generates the Block Kit view for the App Home."""
    # Fetch current filter state
    current_filter = filter_store.get_filter(user_id)
    filter_status = (
        f"Running locally on *'{current_filter}'*"
        if current_filter
        else "Running on *All Quotes* (Random)"
    )

    return {
        "type": "home",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🤖 Welcome to StatusQuo",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"👋 *Hello, <@{user_id}>!* \n\nI manage your Slack status so you don't have to. I update it automatically every morning at 9:00 AM.",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"⚙️ *Current Settings:*\n{filter_status}",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🔄 Force Update Now",
                            "emoji": True,
                        },
                        "style": "primary",
                        "action_id": "home_refresh_status",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "➕ Add New Quote",
                            "emoji": True,
                        },
                        "action_id": "home_open_add_modal",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🗑️ Clear Filter",
                            "emoji": True,
                        },
                        "style": "danger",
                        "action_id": "home_clear_filter",
                    },
                ],
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Need help? Check the <https://github.com/scavara/statusquo|Documentation> or contact support.",
                    }
                ],
            },
        ],
    }


@app.event("app_home_opened")
def update_home_tab(client, event, logger):
    try:
        client.views_publish(user_id=event["user"], view=get_home_view(event["user"]))
    except Exception as e:
        logger.error(f"Error publishing home tab: {e}")


# ==========================================
# 2. HOME TAB ACTIONS & MODALS
# ==========================================


@app.action("home_refresh_status")
def action_refresh_status(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    team_id = body["team"]["id"]

    # --- RATE LIMIT CHECK ---
    allowed, msg = limiter.check_update_limit(user_id)
    if not allowed:
        try:
            client.chat_postEphemeral(channel=user_id, user=user_id, text=msg)
        except SlackApiError:
            pass
        return

    installation = installation_store.find_installation(
        enterprise_id=body.get("enterprise_id"), team_id=team_id
    )

    if not installation or installation.user_id != user_id:
        try:
            client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
                text="⚠️ I don't have permission to update your status. Please reinstall the app.",
            )
        except SlackApiError:
            pass
        return

    # Log attempt *before* work is done
    limiter.log_update_attempt(user_id)

    success, result_msg = perform_user_update(
        installation=installation,
        client=client,
        filter_store=filter_store,
        quotes_table=quotes_table,
    )

    msg = (
        f"✅ Status updated: {result_msg}"
        if success
        else f"❌ Update failed: {result_msg}"
    )

    # Notify user in App Home messages tab
    client.chat_postMessage(channel=user_id, text=msg)


@app.action("home_clear_filter")
def action_clear_filter(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    filter_store.clear_filter(user_id)

    # Refresh the Home Tab to show the new state
    client.views_publish(user_id=user_id, view=get_home_view(user_id))


@app.action("home_open_add_modal")
def action_open_modal(ack, body, client):
    ack()
    user_id = body["user"]["id"]

    # --- RATE LIMIT CHECK ---
    allowed, msg = limiter.check_add_limit(user_id)
    if not allowed:
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "Limit Reached"},
                "close": {"type": "plain_text", "text": "Got it"},
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": msg}}
                ],
            },
        )
        return

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "modal_submit_quote",
            "title": {"type": "plain_text", "text": "Add a Quote"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "input_text",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "val",
                        "multiline": True,
                        "max_length": 80,
                    },
                    "label": {"type": "plain_text", "text": "Quote Text"},
                },
                {
                    "type": "input",
                    "block_id": "input_author",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "val",
                        "max_length": 20,
                    },
                    "label": {"type": "plain_text", "text": "Author"},
                },
                {
                    "type": "input",
                    "block_id": "input_emoji",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "val",
                        "placeholder": {"type": "plain_text", "text": ":wave:"},
                    },
                    "label": {"type": "plain_text", "text": "Emoji"},
                },
            ],
        },
    )


@app.view("modal_submit_quote")
def handle_modal_submission(ack, body, client, view):
    ack()

    # 1. Extract Data
    values = view["state"]["values"]
    text = values["input_text"]["val"]["value"]
    author = values["input_author"]["val"]["value"]
    emoji = values["input_emoji"]["val"]["value"]
    user_id = body["user"]["id"]

    # 2. Basic Validation
    if not (emoji.startswith(":") and emoji.endswith(":")):
        ack(
            response_action="errors",
            errors={"input_emoji": "Must start and end with colons. e.g. :rocket:"},
        )
        return

    # 3. Create Proposal
    proposal_data = json.dumps(
        {"text": text, "author": author, "emoji": emoji, "proposer": user_id}
    )

    # 4. Increment Pending Count
    limiter.increment_pending(user_id)

    # 5. Send approval to user (Self-Approval)
    client.chat_postMessage(
        channel=user_id,
        text="New Quote Request",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f'*New Quote Request:*\n> {emoji} "{text}"\n> -- _{author}_\n_Requested by <@{user_id}>_',
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
                        "value": proposal_data,  # Required for rate limiting logic
                    },
                ],
            },
        ],
    )


# ==========================================
# 3. SLASH COMMANDS (Legacy / Power User)
# ==========================================


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
    enterprise_id = body.get("enterprise_id")

    # 1. Try to find an installation SPECIFICALLY for this user
    # We pass 'user_id' so the store looks for THIS user's tokens, not just the team bot token.
    installation = installation_store.find_installation(
        enterprise_id=enterprise_id,
        team_id=team_id,
        user_id=user_id
    )

    # 2. If we don't have a token for this specific user, ask them to auth
    if not installation or not installation.user_token:
        # Construct the install URL so they can click and authorize immediately
        # We try to grab the current server URL dynamically
        try:
            base_url = request.url_root.rstrip("/")
            # Ensure HTTPS if on Heroku (Heroku forwards http internal requests)
            if "herokuapp" in base_url and base_url.startswith("http://"):
                base_url = base_url.replace("http://", "https://")
            install_url = f"{base_url}/slack/install"
        except Exception:
            install_url = "/slack/install" # Fallback

        respond(
            f"⚠️ *I don't have permission to update your status yet.*\n"
            f"Since status updates require access to your personal profile, you need to authorize me first.\n\n"
            f"👉 <{install_url}|Click here to Authorize StatusQuo>"
        )
        return

    respond("🔄 Updating your status now...")

    # 3. Perform the update using the found user token
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


@app.command("/quo-add")
def handle_add_command(ack, body, respond):
    """Handles: /quo-add "Quote" | Author | :emoji:"""
    ack()
    user_input = body.get("text", "").strip()
    user_id = body["user_id"]

    # --- RATE LIMIT CHECK ---
    allowed, msg = limiter.check_add_limit(user_id)
    if not allowed:
        respond(msg)
        return

    parts = user_input.split("|")
    if len(parts) != 3:
        respond(text="⚠️ Format required: `/quo-add Quote Text | Author Name | :emoji:`")
        return

    clean_text = parts[0].strip().strip('"').strip("'")
    clean_author = parts[1].strip()
    clean_emoji = parts[2].strip()

    if not (clean_emoji.startswith(":") and clean_emoji.endswith(":")):
        respond(f"⚠️ Invalid emoji format: `{clean_emoji}`.")
        return

    predicted_status = f'"{clean_text}." --{clean_author}'
    if len(predicted_status) > 100:
        overage = len(predicted_status) - 100
        respond(f"⚠️ *Quote is too long!* Please shorten by {overage} characters.")
        return

    is_duplicate, existing_item = deduplicator.check_exists(clean_text)
    if is_duplicate:
        exist_author = existing_item.get("author", "Unknown")
        respond(f'🛑 *Duplicate Quote Detected!*\n> "{clean_text}" -- {exist_author}')
        return

    proposal_data = json.dumps(
        {
            "text": clean_text,
            "author": clean_author,
            "emoji": clean_emoji,
            "proposer": user_id,
        }
    )

    # Increment Pending
    limiter.increment_pending(user_id)

    respond(
        response_type="in_channel",
        text="New Quote Request",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f'*New Quote Request:*\n> {clean_emoji} "{clean_text}"\n> -- _{clean_author}_\n_Requested by <@{user_id}>_',
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
                        "value": proposal_data,  # Required for rate limiting logic
                    },
                ],
            },
        ],
    )


@app.command("/quo-filter")
def handle_filter_command(ack, body, respond):
    """Handles: /quo-filter Mark (matches Mark Twain, etc.), list, or flush"""
    ack()
    user_input = body.get("text", "").strip()
    user_id = body["user_id"]

    if not user_input:
        respond(
            "⚠️ Usage: `/quo-filter <Author Name>`, `/quo-filter list`, or `/quo-filter flush`"
        )
        return

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

    author_partial = user_input.replace('"', "").replace("'", "")

    try:
        response = quotes_table.scan(
            FilterExpression=Attr("author").contains(author_partial)
        )

        if response["Count"] == 0:
            respond(f"⚠️ I couldn't find any quotes matching *'{author_partial}'*.")
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
# 4. SHARED ACTIONS
# ==========================================


@app.action("approve_quote")
def handle_approval(ack, body, respond):
    ack()
    action_value = body["actions"][0]["value"]
    data = json.loads(action_value)

    # Decrement pending count / Increment daily count
    proposer_id = data.get("proposer", body["user"]["id"])
    limiter.process_approval(proposer_id)

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
    action_value = body["actions"][0]["value"]
    data = json.loads(action_value)

    # Decrement pending count
    proposer_id = data.get("proposer", body["user"]["id"])
    limiter.process_denial(proposer_id)

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
# 5. FLASK ROUTES & LEGAL PAGES
# ==========================================


@flask_app.route("/", methods=["GET"])
def index():
    return INDEX_HTML


@flask_app.route("/privacy", methods=["GET"])
def privacy():
    return PRIVACY_HTML


@flask_app.route("/support", methods=["GET"])
def support():
    return SUPPORT_HTML


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
