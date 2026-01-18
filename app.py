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

# GOOGLE AUTH CONFIG (Add these to .env)
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
# Generate a random secret key for Flask sessions: `openssl rand -hex 32`
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev_secret_key")
ADMIN_EMAILS = os.environ.get("ADMIN_EMAILS", "").split(",") # e.g. "me@gmail.com,you@gmail.com"

# --- AWS DYNAMODB SETUP ---
dynamodb = boto3.resource("dynamodb")
quotes_table = dynamodb.Table("FunQuotes")
pending_table = dynamodb.Table("FunQuotePending") # <--- NEW TABLE
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
    )
)

flask_app = Flask(__name__)
flask_app.secret_key = FLASK_SECRET_KEY
handler = SlackRequestHandler(app)

# --- OAUTH SETUP ---
oauth = OAuth(flask_app)
oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)


# ==========================================
# 1. NEW COMMAND: /quo-search
# ==========================================
@app.command("/quo-search")
def handle_search_command(ack, body, respond):
    """Searches for an EXACT match in the approved database."""
    ack()
    query = body.get("text", "").strip()
    
    if not query:
        respond("⚠️ usage: `/quo-search \"Quote Text\"`")
        return
        
    clean_query = query.replace('"', '').replace("'", "").strip()
    
    respond(f"🔍 Searching for: _{clean_query}_ ...")
    
    try:
        # Scan is inefficient for massive DBs, but fine for <10k quotes
        response = quotes_table.scan(
            FilterExpression=Attr("text").eq(clean_query)
        )
        
        items = response.get("Items", [])
        
        if items:
            item = items[0]
            respond(f"✅ **Found it!** This quote is approved and active.\n> {item['emoji']} \"{item['text']}\" --{item['author']}")
        else:
            respond(f"🕵️ **Not found.** It might still be in the review queue (check back in ~1 hour) or it was denied.")
            
    except Exception as e:
        respond(f"❌ Database error: {e}")


# ==========================================
# 2. UPDATED COMMAND: /quo-add (No more buttons)
# ==========================================
@app.command("/quo-add")
def handle_add_command(ack, body, respond):
    ack()
    user_input = body.get("text", "").strip()
    user_id = body["user_id"]

    # --- RATE LIMIT CHECK ---
    allowed, msg = limiter.check_add_limit(user_id)
    if not allowed:
        respond(msg)
        return

    # --- PARSE & VALIDATE ---
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

    # Check Duplicates (Approved DB)
    is_duplicate, _ = deduplicator.check_exists(clean_text)
    if is_duplicate:
        respond(f"🛑 We already have that quote!")
        return

    # --- SAVE TO PENDING TABLE ---
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
                "created_at": str(uuid.uuid1().time) # Simple timestamp approximation
            }
        )
        limiter.increment_pending(user_id)
        
        respond(
            f"✅ **Submission Received!**\n"
            f"> {clean_emoji} \"{clean_text}\"\n"
            f"Your quote is now in the review queue. Please check back in **1 hour** using `/quo-search`."
        )
    except Exception as e:
        respond(f"❌ Error saving submission: {e}")


# ==========================================
# 3. EXISTING COMMANDS (Update, Filter) - Kept Brief
# ==========================================
@app.command("/quo-update")
def handle_update(ack, body, respond):
    ack()
    # ... (Insert your existing update logic here, ensuring user_id checks) ...
    # For brevity in this snippet, assuming you copy-paste the fixed logic we discussed earlier.
    respond("Please implement update logic copy-paste from previous steps.")

@app.command("/quo-filter")
def handle_filter(ack, body, respond):
    ack()
    # ... (Insert your existing filter logic) ...
    respond("Please implement filter logic copy-paste from previous steps.")


# ==========================================
# 4. ADMIN WEB UI ROUTES
# ==========================================

@flask_app.route("/admin")
def admin_dashboard():
    user = session.get('user')
    if not user:
        return LOGIN_HTML
    
    # Check if user is in ALLOWED_EMAILS
    if user['email'] not in ADMIN_EMAILS:
        return "🚫 Access Denied. Your email is not an authorized admin."

    # Fetch Pending Quotes
    try:
        response = pending_table.scan()
        quotes = response.get("Items", [])
    except Exception as e:
        return f"Database Error: {e}"

    return render_template_string(DASHBOARD_TEMPLATE, quotes=quotes, user=user)

@flask_app.route('/admin/google')
def google_login():
    redirect_uri = url_for('google_auth', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@flask_app.route('/admin/auth')
def google_auth():
    token = oauth.google.authorize_access_token()
    session['user'] = token['userinfo']
    return redirect('/admin')

@flask_app.route('/admin/logout')
def logout():
    session.pop('user', None)
    return redirect('/admin')

@flask_app.route('/admin/approve/<quote_id>', methods=['POST'])
def admin_approve(quote_id):
    if not session.get('user'): return redirect('/admin')
    
    # 1. Get the item from Pending
    resp = pending_table.get_item(Key={'quote_id': quote_id})
    item = resp.get('Item')
    
    if item:
        # 2. Save to Prod
        quotes_table.put_item(
            Item={
                'quote_id': item['quote_id'],
                'text': item['text'],
                'author': item['author'],
                'emoji': item['emoji']
            }
        )
        # 3. Delete from Pending
        pending_table.delete_item(Key={'quote_id': quote_id})
        
        # 4. Update Stats
        limiter.process_approval(item['proposer'])
        
    return redirect('/admin')

@flask_app.route('/admin/deny/<quote_id>', methods=['POST'])
def admin_deny(quote_id):
    if not session.get('user'): return redirect('/admin')
    
    # 1. Get Item (for proposer ID)
    resp = pending_table.get_item(Key={'quote_id': quote_id})
    item = resp.get('Item')

    # 2. Delete
    pending_table.delete_item(Key={'quote_id': quote_id})
    
    # 3. Update Stats
    if item:
        limiter.process_denial(item['proposer'])
        
    return redirect('/admin')


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
    flask_app.run(host="0.0.0.0", port=port)
