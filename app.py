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
from slack_sdk.oauth.installation_store import InstallationStore, Installation
from slack_sdk.oauth.state_store import FileStateStore
from apscheduler.schedulers.background import BackgroundScheduler

# --- CONFIGURATION ---
SLACK_CLIENT_ID = os.environ["SLACK_CLIENT_ID"]
SLACK_CLIENT_SECRET = os.environ["SLACK_CLIENT_SECRET"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
# Scopes needed for the bot to work
SCOPES = ["commands", "chat:write"]
# Scopes needed to update the user's status
USER_SCOPES = ["users.profile:write"]

# --- AWS DYNAMODB SETUP ---
dynamodb = boto3.resource('dynamodb')
quotes_table = dynamodb.Table('FunQuotes')
install_table = dynamodb.Table('SlackInstallations')

# --- CUSTOM INSTALLATION STORE (MULTI-TENANT) ---
class DynamoDBInstallationStore(InstallationStore):
    def save(self, installation: Installation):
        # Save the token data to DynamoDB
        # We use a composite key of team_id and user_id to handle specific user tokens
        item = {
            'client_id': installation.client_id,
            'enterprise_or_team_id': installation.team_id,
            'installation_data': json.dumps(installation.to_dict())
        }
        install_table.put_item(Item=item)

    def find_installation(self, enterprise_id, team_id, user_id=None, is_enterprise_install=False):
        # Retrieve token based on team_id
        try:
            response = install_table.get_item(
                Key={
                    'client_id': SLACK_CLIENT_ID,
                    'enterprise_or_team_id': team_id
                }
            )
            if 'Item' in response:
                data = json.loads(response['Item']['installation_data'])
                return Installation(**data)
        except Exception as e:
            logging.error(f"Find installation error: {e}")
        return None

# --- APP INITIALIZATION ---
oauth_settings = OAuthSettings(
    client_id=SLACK_CLIENT_ID,
    client_secret=SLACK_CLIENT_SECRET,
    scopes=SCOPES,
    user_scopes=USER_SCOPES,
    installation_store=DynamoDBInstallationStore(),
    state_store=FileStateStore(base_dir="./data") # Simple local state store for the handshake
)

app = App(
    signing_secret=SLACK_SIGNING_SECRET,
    oauth_settings=oauth_settings
)
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# --- HELPER FUNCTIONS ---
def get_random_quote_from_aws():
    """Fetches all quotes and returns a random one."""
    try:
        response = quotes_table.scan()
        items = response.get('Items', [])
        if not items:
            return {"text": "Default quote", "author": "Bot", "emoji": ":robot_face:"}
        return random.choice(items)
    except Exception as e:
        logging.error(f"AWS Error: {e}")
        return {"text": "AWS Error", "author": "System", "emoji": ":warning:"}

def global_status_update():
    print("⏰ Starting Global Status Update...")
    
    quote = get_random_quote_from_aws()
    author_text = quote.get('author', 'Anonymous')
    full_status = f'"{quote["text"]}." --{author_text}'
    if len(full_status) > 100:
        full_status = full_status[:97] + "..."

    try:
        response = install_table.scan()
        installations = response.get('Items', [])
        
        for item in installations:
            try:
                # 1. Rehydrate the Installation object
                data = json.loads(item['installation_data'])
                installation = Installation(**data)
                
                # --- NEW SECURITY LOGIC START ---
                # Check if token is expired (or expires in the next 5 minutes)
                # 'is_expired()' is a built-in method of the Installation class
                if installation.is_expired():
                    print(f"♻️ Token expired for team {installation.team_name}. Refreshing...")
                    
                    # Perform the Refresh
                    refresh_response = app.client.oauth_v2_access(
                        client_id=SLACK_CLIENT_ID,
                        client_secret=SLACK_CLIENT_SECRET,
                        grant_type="refresh_token",
                        refresh_token=installation.user_refresh_token
                    )
                    
                    # Update the Installation Object with new credentials
                    installation.user_token = refresh_response["access_token"]
                    installation.user_refresh_token = refresh_response["refresh_token"]
                    installation.user_token_expires_at = int(time.time()) + refresh_response["expires_in"]
                    
                    # IMPORTANT: Save the new credentials back to DynamoDB
                    # Your existing store.save() method handles the overwrite
                    oauth_settings.installation_store.save(installation)
                    print("✅ Token refreshed and saved.")
                # --- NEW SECURITY LOGIC END ---

                # Now proceed safely with the valid token
                if installation.user_token:
                    app.client.users_profile_set(
                        token=installation.user_token,
                        profile={
                            "status_text": full_status,
                            "status_emoji": quote['emoji'],
                            "status_expiration": 0
                        }
                    )
                    print(f"✅ Updated status for team {installation.team_name}")
                    
            except Exception as inner_e:
                print(f"❌ Failed for one tenant: {inner_e}")

    except Exception as e:
        print(f"❌ Error scanning installations: {e}")

# --- COMMANDS & ACTIONS ---
@app.command("/quo")
def handle_command(ack, body, respond):
    ack()
    full_text = body.get('text', '').strip()

    if not full_text:
        # Note: We can only force update for THIS user in this context
        respond("🔄 Triggering a global update (this might take a moment)...")
        global_status_update() 
        return

    if full_text.lower().startswith("add"):
        payload = full_text[3:].strip()
        handle_add_quote(payload, body, respond)
        return

    respond("⚠️ Unknown subcommand. Try `/quo` or `/quo add Quote | Author | :emoji:`")

def handle_add_quote(user_input, body, respond):
    parts = user_input.split("|")
    if len(parts) != 3:
        respond(text="⚠️ Format required: `/quo add Quote Text | Author Name | :emoji:`")
        return

    clean_text = parts[0].strip().strip('"').strip("'")
    clean_author = parts[1].strip()
    clean_emoji = parts[2].strip()

    proposal_data = json.dumps({
        "text": clean_text,
        "author": clean_author,
        "emoji": clean_emoji,
        "proposer": body['user_id']
    })

    respond(
        response_type="in_channel",
        text="New Quote Request",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*New Quote Request:*\n> {clean_emoji} \"{clean_text}\"\n> -- _{clean_author}_\n_Requested by <@{body['user_id']}>_"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "style": "primary", "action_id": "approve_quote", "value": proposal_data},
                    {"type": "button", "text": {"type": "plain_text", "text": "Deny"}, "style": "danger", "action_id": "deny_quote"}
                ]
            }
        ]
    )

@app.action("approve_quote")
def handle_approval(ack, body, respond):
    ack()
    action_value = body['actions'][0]['value']
    data = json.loads(action_value)
    quote_id = str(uuid.uuid4())

    try:
        quotes_table.put_item(
            Item={
                'quote_id': quote_id,
                'text': data['text'],
                'author': data['author'],
                'emoji': data['emoji']
            }
        )
        respond(
            text="Quote Approved!",
            replace_original=True,
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": f"✅ *Approved by <@{body['user']['id']}>*\n> {data['emoji']} \"{data['text']}\" --{data['author']}"}}]
        )
    except Exception as e:
        respond(text=f"❌ Error saving quote: {e}")

@app.action("deny_quote")
def handle_denial(ack, body, respond):
    ack()
    respond(
        text="Quote Denied",
        replace_original=True,
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": f"❌ *Denied by <@{body['user']['id']}>*"}}]
    )

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

# --- RUNNER ---
if __name__ == "__main__":
    # Scheduler runs in the background
    scheduler = BackgroundScheduler()
    scheduler.add_job(global_status_update, 'cron', hour=9, minute=0)
    scheduler.start()
    
    print("⚡️ StatusQuo Multi-Tenant is running on port 3000!")
    # Turn off reloader to prevent scheduler running twice
    flask_app.run(host="0.0.0.0", port=3000, debug=False, use_reloader=False)
