import os
import time
import logging
from slack_bolt import App
import boto3

# --- LOCAL IMPORTS ---
from lib.installation_store import DynamoDBInstallationStore
from lib.filter_store import FilterStore
from lib.status_logic import perform_user_update # <-- New Import

# --- SETUP ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SLACK_CLIENT_ID = os.environ["SLACK_CLIENT_ID"]
SLACK_CLIENT_SECRET = os.environ["SLACK_CLIENT_SECRET"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

app = App(
    signing_secret=SLACK_SIGNING_SECRET,
    token="xoxb-placeholder",
)

dynamodb = boto3.resource('dynamodb')
quotes_table = dynamodb.Table('FunQuotes')
installation_store = DynamoDBInstallationStore(client_id=SLACK_CLIENT_ID)
filter_store = FilterStore()

def run_update():
    logger.info("⏰ Starting Daily Status Update...")
    
    installations = installation_store.get_all_installations()
    logger.info(f"Found {len(installations)} installations.")

    for installation in installations:
        try:
            # 1. TOKEN ROTATION (Keep this here, it's infra logic)
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

            # 2. UPDATE STATUS (Use Shared Logic)
            if installation.user_token:
                success, msg = perform_user_update(
                    installation=installation,
                    client=app.client,
                    filter_store=filter_store,
                    quotes_table=quotes_table
                )
                if success:
                    logger.info(f"✅ Updated {installation.user_id}: {msg}")
                else:
                    logger.warning(f"⚠️ Failed {installation.user_id}: {msg}")
                
        except Exception as e:
            logger.error(f"❌ Critical loop error: {e}")

if __name__ == "__main__":
    run_update()
