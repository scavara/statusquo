import os
import time
import random
import boto3
import logging
from slack_bolt import App
from boto3.dynamodb.conditions import Key

# Reuse our stores
from lib.installation_store import DynamoDBInstallationStore
from lib.filter_store import FilterStore

# --- SETUP ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SLACK_CLIENT_ID = os.environ["SLACK_CLIENT_ID"]
SLACK_CLIENT_SECRET = os.environ["SLACK_CLIENT_SECRET"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

# Initialize App (We only need the client logic here)
app = App(
    signing_secret=SLACK_SIGNING_SECRET,
    token="xoxb-placeholder", # We won't use this, we use individual tokens
)

# Database
dynamodb = boto3.resource('dynamodb')
quotes_table = dynamodb.Table('FunQuotes')
installation_store = DynamoDBInstallationStore(client_id=SLACK_CLIENT_ID)
filter_store = FilterStore()

def get_quote_for_user(user_id):
    """Smart fetch using GSI or Fallback."""
    author_filter = filter_store.get_filter(user_id)
    
    if author_filter:
        # FAST Query using the Index we created
        try:
            response = quotes_table.query(
                IndexName='AuthorIndex',
                KeyConditionExpression=Key('author').eq(author_filter)
            )
            items = response.get('Items', [])
            if items:
                return random.choice(items)
            else:
                logger.warning(f"User {user_id} has filter {author_filter} but no quotes found.")
        except Exception as e:
            logger.error(f"GSI Query failed: {e}")

    # Fallback: Scan (random)
    # Optimization: For very large tables, don't scan. Keep a 'QuotesCount' metadata item.
    response = quotes_table.scan()
    items = response.get('Items', [])
    if items:
        return random.choice(items)
    return {"text": "No quotes available", "author": "System", "emoji": ":x:"}

def run_update():
    logger.info("⏰ Starting Daily Status Update...")
    
    installations = installation_store.get_all_installations()
    logger.info(f"Found {len(installations)} installations.")

    for installation in installations:
        try:
            # 1. TOKEN ROTATION
            current_ts = int(time.time())
            if (installation.user_token_expires_at is not None and 
                installation.user_token_expires_at < (current_ts + 300)):
                
                logger.info(f"♻️ Refreshing token for {installation.team_name}")
                refresh = app.client.oauth_v2_access(
                    client_id=SLACK_CLIENT_ID,
                    client_secret=SLACK_CLIENT_SECRET,
                    grant_type="refresh_token",
                    refresh_token=installation.user_refresh_token
                )
                installation.user_token = refresh["access_token"]
                installation.user_refresh_token = refresh["refresh_token"]
                installation.user_token_expires_at = int(time.time()) + refresh["expires_in"]
                installation_store.save(installation)

            # 2. UPDATE STATUS
            if installation.user_token:
                # Use the user_id from the installation to find their filter
                user_id = installation.user_id 
                quote = get_quote_for_user(user_id)

                author = quote.get('author', 'Anonymous')
                text = f'"{quote["text"]}." --{author}'
                if len(text) > 100: text = text[:97] + "..."

                app.client.users_profile_set(
                    token=installation.user_token,
                    profile={
                        "status_text": text,
                        "status_emoji": quote['emoji'],
                        "status_expiration": 0
                    }
                )
                logger.info(f"✅ Updated {installation.user_id} ({author})")
                
        except Exception as e:
            logger.error(f"❌ Failed for installation {installation.team_id}: {e}")

if __name__ == "__main__":
    run_update()
