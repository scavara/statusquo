import os
import json
import uuid
import boto3
from flask import Flask, request, session, redirect, url_for, render_template_string
from authlib.integrations.flask_client import OAuth
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_bolt.oauth.oauth_settings import OAuthSettings
from slack_sdk.oauth.state_store import FileOAuthStateStore
from boto3.dynamodb.conditions import Attr

# --- LOCAL IMPORTS ---
from lib.installation_store import DynamoDBInstallationStore
from lib.filter_store import FilterStore
from lib.status_logic import perform_user_update
from lib.quote_deduplicator import QuoteDeduplicator
from lib.legal_pages import PRIVACY_HTML, SUPPORT_HTML, INDEX_HTML
from lib.rate_limiter import RateLimiter
from lib.admin_ui import DASHBOARD_TEMPLATE, LOGIN_HTML

# --- CONFIGURATION ---
SLACK_CLIENT_ID = os.environ["SLACK_CLIENT_ID"]
SLACK_CLIENT_SECRET = os.environ["SLACK_CLIENT_SECRET"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

# GOOGLE AUTH CONFIG
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev_secret_key")
ADMIN_EMAILS = os.environ.get("ADMIN_EMAILS", "").split(",")

# --- AWS DYNAMODB SETUP ---
dynamodb = boto3.resource("dynamodb")
quotes_table = dynamodb.Table("FunQuotes")
pending_table = dynamodb.Table("FunQuotePending")
deduplicator = QuoteDeduplicator(quotes_table)
limiter = RateLimiter(quotes_table)

# --- STORES ---
installation_store = DynamoDBInstallationStore(client_id=SLACK_CLIENT_ID)
filter_store = FilterStore()

# --- APP SETUP ---
app = App(
    signing_secret=SLACK_SIGNING_SECRET,
    oauth_settings=OAuthSettings(
        client_id=SLACK_CLIENT_ID,
        client_secret=SLACK_CLIENT_SECRET,
        scopes=["commands", "chat:write"],
        user_scopes=["users.profile:write"],
        installation_store=installation_store,
        state_store=FileOAuthStateStore(expiration_seconds=600, base_dir="./data"),
    ),
)

flask_app = Flask(__name__)
flask_app.secret_key = FLASK_SECRET_KEY
handler = SlackRequestHandler(app)

# --- OAUTH SETUP ---
oauth = OAuth(flask_app)
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# ==========================================
# 1. APP HOME TAB (VISUAL INTERFACE)
# ==========================================


def get_home_view(user_id):
    """Generates the Block Kit view for the App Home."""
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
                    "text": f"👋 *Hello, <@{user_id}>!* \n\nI manage your Slack status automatically. You can also search the database to check if your favorite quote is already approved.",
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
                            "text": "🔄 Update Status",
                            "emoji": True,
                        },
                        "style": "primary",
                        "action_id": "home_refresh_status",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "➕ Add Quote",
                            "emoji": True,
                        },
                        "action_id": "home_open_add_modal",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🔍 Search",
                            "emoji": True,
                        },
                        "action_id": "home_open_search_modal",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🗑️ Reset",
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
                        "text": "Need help? Check the <https://github.com/scavara/statusquo|Documentation> or use `/quo-search`.",
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

    # Rate Limit
    allowed, msg = limiter.check_update_limit(user_id)
    if not allowed:
        client.chat_postEphemeral(channel=user_id, user=user_id, text=msg)
        return

    # User-specific installation check
    installation = installation_store.find_installation(
        enterprise_id=body.get("enterprise_id"), team_id=team_id, user_id=user_id
    )

    if not installation or not installation.user_token:
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="⚠️ I don't have permission to update your status. Please <https://statusquo.herokuapp.com/slack/install|authorize the app> first.",
        )
        return

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
    client.chat_postMessage(channel=user_id, text=msg)


@app.action("home_clear_filter")
def action_clear_filter(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    filter_store.clear_filter(user_id)
    client.views_publish(user_id=user_id, view=get_home_view(user_id))


@app.action("home_open_add_modal")
def action_open_modal(ack, body, client):
    ack()
    user_id = body["user"]["id"]

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
    values = view["state"]["values"]
    text = values["input_text"]["val"]["value"]
    author = values["input_author"]["val"]["value"]
    emoji = values["input_emoji"]["val"]["value"]
    user_id = body["user"]["id"]

    if not (emoji.startswith(":") and emoji.endswith(":")):
        ack(
            response_action="errors",
            errors={"input_emoji": "Must use colons e.g. :wave:"},
        )
        return

    # Deduplication check
    is_duplicate, _ = deduplicator.check_exists(text)
    if is_duplicate:
        client.chat_postMessage(
            channel=user_id, text=f'🛑 We already have the quote: "{text}"'
        )
        return

    # Save to Pending Table
    quote_id = str(uuid.uuid4())
    try:
        pending_table.put_item(
            Item={
                "quote_id": quote_id,
                "text": text,
                "author": author,
                "emoji": emoji,
                "proposer": user_id,
                "status": "PENDING",
                "created_at": str(uuid.uuid1().time),
            }
        )
        limiter.increment_pending(user_id)
        client.chat_postMessage(
            channel=user_id,
            text=f"✅ Quote submitted for review! Check back in 1 hour using `/quo-search`.",
        )
    except Exception as e:
        client.chat_postMessage(
            channel=user_id, text=f"❌ Error saving submission: {e}"
        )


@app.action("home_open_search_modal")
def action_open_search_modal(ack, body, client):
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "modal_search_submit",
            "title": {"type": "plain_text", "text": "Search Database"},
            "submit": {"type": "plain_text", "text": "Search"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "search_input",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "value",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "e.g. coffee, yoda",
                        },
                        "min_length": 3,
                    },
                    "label": {"type": "plain_text", "text": "Find a quote"},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "plain_text",
                            "text": "Searches for text matches in approved quotes.",
                        }
                    ],
                },
            ],
        },
    )


@app.view("modal_search_submit")
def handle_search_modal(ack, body, client, view):
    ack()
    user_id = body["user"]["id"]
    query = view["state"]["values"]["search_input"]["value"]["value"].strip()

    try:
        response = quotes_table.scan(FilterExpression=Attr("text").contains(query))
        items = response.get("Items", [])

        if items:
            results_text = f"✅ *Found {len(items)} match(es) for '{query}':*\n"
            for item in items[:3]:
                results_text += (
                    f"> {item['emoji']} \"{item['text']}\" --_{item['author']}_\n"
                )
            if len(items) > 3:
                results_text += f"_...and {len(items)-3} more._"
        else:
            results_text = f"🕵️ No approved quotes found matching *'{query}'*."

        client.chat_postMessage(channel=user_id, text=results_text)
    except Exception as e:
        client.chat_postMessage(channel=user_id, text=f"❌ Error: {e}")


# ==========================================
# 3. SLASH COMMANDS
# ==========================================


@app.command("/quo-search")
def handle_search_command(ack, body, respond):
    ack()
    query = body.get("text", "").strip()
    if not query:
        respond('⚠️ usage: `/quo-search "Quote Text"`')
        return
    clean_query = query.replace('"', "").replace("'", "").strip()

    respond(f"🔍 Searching for: _{clean_query}_ ...")
    try:
        response = quotes_table.scan(FilterExpression=Attr("text").eq(clean_query))
        items = response.get("Items", [])
        if items:
            item = items[0]
            respond(
                f"✅ **Found it!**\n> {item['emoji']} \"{item['text']}\" --{item['author']}"
            )
        else:
            respond(f"🕵️ **Not found.** It might be pending review or denied.")
    except Exception as e:
        respond(f"❌ Database error: {e}")


@app.command("/quo-add")
def handle_add_command(ack, body, respond):
    ack()
    user_input = body.get("text", "").strip()
    user_id = body["user_id"]

    allowed, msg = limiter.check_add_limit(user_id)
    if not allowed:
        respond(msg)
        return

    parts = user_input.split("|")
    if len(parts) != 3:
        respond(text="⚠️ Format: `/quo-add Quote | Author | :emoji:`")
        return

    clean_text = parts[0].strip().strip('"')
    clean_author = parts[1].strip()
    clean_emoji = parts[2].strip()

    if not (clean_emoji.startswith(":") and clean_emoji.endswith(":")):
        respond(f"⚠️ Invalid emoji: `{clean_emoji}`")
        return

    is_duplicate, _ = deduplicator.check_exists(clean_text)
    if is_duplicate:
        respond(f"🛑 We already have that quote!")
        return

    quote_id = str(uuid.uuid4())
    try:
        pending_table.put_item(
            Item={
                "quote_id": quote_id,
                "text": clean_text,
                "author": clean_author,
                "emoji": clean_emoji,
                "proposer": user_id,
                "status": "PENDING",
                "created_at": str(uuid.uuid1().time),
            }
        )
        limiter.increment_pending(user_id)
        respond(f"✅ **Submission Received!** Check back in 1 hour.")
    except Exception as e:
        respond(f"❌ Error saving submission: {e}")


@app.command("/quo-update")
def handle_update_command(ack, body, respond):
    ack()
    user_id = body["user_id"]
    team_id = body["team_id"]
    enterprise_id = body.get("enterprise_id")

    allowed, msg = limiter.check_update_limit(user_id)
    if not allowed:
        respond(msg)
        return

    # Explicitly pass user_id to find THIS user's token
    installation = installation_store.find_installation(
        enterprise_id=enterprise_id, team_id=team_id, user_id=user_id
    )

    if not installation or not installation.user_token:
        # Construct dynamic install URL if possible, else fallback
        try:
            base_url = request.url_root.rstrip("/")
            if "herokuapp" in base_url and base_url.startswith("http://"):
                base_url = base_url.replace("http://", "https://")
            install_url = f"{base_url}/slack/install"
        except Exception:
            install_url = "/slack/install"

        respond(
            f"⚠️ Permission Denied. Please <{install_url}|Authorize StatusQuo> first."
        )
        return

    respond("🔄 Updating your status now...")
    limiter.log_update_attempt(user_id)

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


@app.command("/quo-filter")
def handle_filter_command(ack, body, respond):
    ack()
    user_input = body.get("text", "").strip()
    user_id = body["user_id"]

    if not user_input:
        respond(
            "⚠️ Usage: `/quo-filter <Author>`, `/quo-filter list`, or `/quo-filter flush`"
        )
        return

    if user_input.lower() == "flush":
        if filter_store.clear_filter(user_id):
            respond("🗑️ Filter cleared!")
        else:
            respond("❌ Error.")
        return

    if user_input.lower() == "list":
        current = filter_store.get_filter(user_id)
        msg = f"🔍 Current filter: *{current}*" if current else "No filter active."
        respond(msg)
        return

    author_partial = user_input.replace('"', "").replace("'", "")
    try:
        response = quotes_table.scan(
            FilterExpression=Attr("author").contains(author_partial)
        )
        if response["Count"] == 0:
            respond(f"⚠️ No quotes found matching *'{author_partial}'*.")
        else:
            if filter_store.set_filter(user_id, author_partial):
                respond(f"✅ Filter set for *'{author_partial}'*")
            else:
                respond("❌ Database error.")
    except Exception as e:
        respond(f"❌ Database error: {e}")


# ==========================================
# 4. ADMIN WEB UI ROUTES
# ==========================================


@flask_app.route("/admin")
def admin_dashboard():
    user = session.get("user")
    if not user:
        return LOGIN_HTML
    if user["email"] not in ADMIN_EMAILS:
        return "🚫 Access Denied."

    try:
        response = pending_table.scan()
        quotes = response.get("Items", [])
    except Exception as e:
        return f"Database Error: {e}"
    return render_template_string(DASHBOARD_TEMPLATE, quotes=quotes, user=user)


@flask_app.route("/admin/google")
def google_login():
    redirect_uri = url_for("google_auth", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@flask_app.route("/admin/auth")
def google_auth():
    token = oauth.google.authorize_access_token()
    session["user"] = token["userinfo"]
    return redirect("/admin")


@flask_app.route("/admin/logout")
def logout():
    session.pop("user", None)
    return redirect("/admin")


@flask_app.route("/admin/approve/<quote_id>", methods=["POST"])
def admin_approve(quote_id):
    if not session.get("user"):
        return redirect("/admin")

    # Move from Pending to Approved
    resp = pending_table.get_item(Key={"quote_id": quote_id})
    item = resp.get("Item")
    if item:
        quotes_table.put_item(
            Item={
                "quote_id": item["quote_id"],
                "text": item["text"],
                "author": item["author"],
                "emoji": item["emoji"],
            }
        )
        pending_table.delete_item(Key={"quote_id": quote_id})
        limiter.process_approval(item["proposer"])
    return redirect("/admin")


@flask_app.route("/admin/deny/<quote_id>", methods=["POST"])
def admin_deny(quote_id):
    if not session.get("user"):
        return redirect("/admin")

    # Just delete from Pending
    resp = pending_table.get_item(Key={"quote_id": quote_id})
    item = resp.get("Item")
    pending_table.delete_item(Key={"quote_id": quote_id})
    if item:
        limiter.process_denial(item["proposer"])
    return redirect("/admin")


# ==========================================
# 5. PUBLIC ROUTES
# ==========================================
@flask_app.route("/", methods=["GET"])
def index():
    return INDEX_HTML


@flask_app.route("/support", methods=["GET"])
def support():
    return SUPPORT_HTML


@flask_app.route("/privacy", methods=["GET"])
def privacy():
    return PRIVACY_HTML


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
    port = int(os.environ.get("PORT", 3000))
    print(f"⚡️ StatusQuo Web Server running on port {port}!")
    flask_app.run(host="0.0.0.0", port=port)
