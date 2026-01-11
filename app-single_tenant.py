import os
import random
import json
import uuid
import boto3
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from apscheduler.schedulers.background import BackgroundScheduler

# --- CONFIGURATION ---
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
SLACK_USER_TOKEN = os.environ.get("SLACK_USER_TOKEN")
# Optional: Secure the approval button
ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID") 

app = App(token=SLACK_BOT_TOKEN)

# --- AWS DYNAMODB SETUP ---
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('FunQuotes')

# --- HELPER FUNCTIONS ---
def get_random_quote_from_aws():
    """Fetches all quotes and returns a random one."""
    try:
        response = table.scan()
        items = response.get('Items', [])
        if not items:
            return {"text": "Default quote", "author": "Bot", "emoji": ":robot_face:"}
        return random.choice(items)
    except Exception as e:
        print(f"AWS Error: {e}")
        return {"text": "AWS Error", "author": "System", "emoji": ":warning:"}

def set_status():
    print("⏰ Time to update status...")
    quote = get_random_quote_from_aws()
    
    # 1. Format the string: "Quote." --Author
    # We use .get() for author to handle old records that might not have one yet
    author_text = quote.get('author', 'Anonymous')
    full_status = f'"{quote["text"]}." --{author_text}'

    # 2. Safety Check: Slack Status has a strict 100-char limit
    if len(full_status) > 100:
        # Truncate and add ellipsis to fit logic
        # allowed length = 100 - 3 (for "...")
        full_status = full_status[:97] + "..."

    try:
        app.client.users_profile_set(
            token=SLACK_USER_TOKEN,
            profile={
                "status_text": full_status,
                "status_emoji": quote['emoji'],
                "status_expiration": 0
            }
        )
        print(f"✅ Status updated to: {full_status}")
    except Exception as e:
        print(f"❌ Failed to update status: {e}")

# --- SLASH COMMAND ROUTER ---
@app.command("/quo")
def handle_command(ack, body, respond):
    """
    Master command handler.
    1. `/quo` -> Updates Status
    2. `/quo add ...` -> Proposes new quote
    """
    ack()

    # Get the text after the command (e.g., "add Hello | Me | :wave:")
    full_text = body.get('text', '').strip()

    # ROUTE 1: No arguments? Run the Status Update.
    if not full_text:
        respond("🔄 I've forced a status update from the cloud!")
        set_status()
        return

    # ROUTE 2: Starts with "add"? Run the Submission Logic.
    if full_text.lower().startswith("add"):
        # Strip the word "add" from the start to get the raw payload
        # Example: "add quote | author | :emoji:" -> "quote | author | :emoji:"
        payload = full_text[3:].strip()
        handle_add_quote(payload, body, respond)
        return

    # ROUTE 3: Unknown command
    respond("⚠️ Unknown subcommand. Try `/quo` to update status, or `/quo add Quote | Author | :emoji:` to add one.")

def handle_add_quote(user_input, body, respond):
    """Helper function to parse and submit a quote."""

    # EXPECTED FORMAT: "Quote Text | Author Name | :emoji:"
    parts = user_input.split("|")

    if len(parts) != 3:
        respond(text="⚠️ Format required: `/quo add Quote Text | Author Name | :emoji:`")
        return

    clean_text = parts[0].strip()
    # Remove quotes if the user typed them explicitly (optional polish)
    clean_text = clean_text.strip('"').strip("'")

    clean_author = parts[1].strip()
    clean_emoji = parts[2].strip()

    # Pack data into JSON for the button value
    proposal_data = json.dumps({
        "text": clean_text,
        "author": clean_author,
        "emoji": clean_emoji,
        "proposer": body['user_id']
    })

    # Send Approval Message
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
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": "approve_quote",
                        "value": proposal_data
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Deny"},
                        "style": "danger",
                        "action_id": "deny_quote"
                    }
                ]
            }
        ]
    )

# --- ACTIONS (INTERACTIVITY) ---
@app.action("approve_quote")
def handle_approval(ack, body, respond):
    ack()

    action_value = body['actions'][0]['value']
    data = json.loads(action_value)
    quote_id = str(uuid.uuid4())

    try:
        # Save to AWS DynamoDB
        table.put_item(
            Item={
                'quote_id': quote_id,
                'text': data['text'],
                'author': data['author'],
                'emoji': data['emoji']
            }
        )

        # FIX: Use respond() with replace_original=True
        # This works perfectly for messages created by slash commands
        respond(
            text="Quote Approved!",
            replace_original=True, # This overwrites the buttons with the success message
            blocks=[{
                "type": "section",
                "text": {
                    "type": "mrkdwn", 
                    "text": f"✅ *Approved by <@{body['user']['id']}>*\n> {data['emoji']} \"{data['text']}\" --{data['author']}"
                }
            }]
        )
    except Exception as e:
        print(f"Error saving to DynamoDB: {e}")
        respond(text=f"❌ Error saving quote: {e}")

@app.action("deny_quote")
def handle_denial(ack, body, respond):
    ack()
    try:
        # FIX: Use respond() here too
        respond(
            text="Quote Denied",
            replace_original=True,
            blocks=[{
                "type": "section",
                "text": {
                    "type": "mrkdwn", 
                    "text": f"❌ *Denied by <@{body['user']['id']}>*"
                }
            }]
        )
    except Exception as e:
        print(f"Error updating message: {e}")

# --- APP RUNNER ---
if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_job(set_status, 'cron', hour=9, minute=0)
    scheduler.start()
    
    print("⚡️ StatusQuo is running!")
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
