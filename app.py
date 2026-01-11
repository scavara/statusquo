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

# --- SLASH COMMANDS ---

@app.command("/quo")
def manual_trigger(ack, body):
    """Manually forces a status update."""
    ack("🔄 I've forced a status update from the cloud!")
    set_status()

@app.command("/add-quote")
def request_new_quote(ack, body, respond):
    """Submits a new quote for approval."""
    ack()

    user_input = body['text']

    # EXPECTED FORMAT: "Quote Text | Author Name | :emoji:"
    parts = user_input.split("|")

    if len(parts) != 3:
        # We use respond() here to safely reply only to the user
        respond(text="⚠️ Format required: `Quote Text | Author Name | :emoji:`")
        return

    clean_text = parts[0].strip()
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
    # FIX: We use 'respond' instead of 'client.chat_postMessage'.
    # This works in private channels/DMs without needing to invite the bot.
    respond(
        response_type="in_channel", # This makes the card visible to everyone in the channel (so admins can see it)
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
def handle_approval(ack, body, client):
    ack()
    
    # Optional: Check if user is admin
    # if body['user']['id'] != ADMIN_USER_ID: return

    action_value = body['actions'][0]['value']
    data = json.loads(action_value)
    quote_id = str(uuid.uuid4())

    try:
        # Save to AWS with the new 'author' field
        table.put_item(
            Item={
                'quote_id': quote_id,
                'text': data['text'],
                'author': data['author'],
                'emoji': data['emoji']
            }
        )
        
        # Update message to remove buttons
        client.chat_update(
            channel=body['channel']['id'],
            ts=body['message']['ts'],
            text="Quote Approved!",
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

@app.action("deny_quote")
def handle_denial(ack, body, client):
    ack()
    client.chat_update(
        channel=body['channel']['id'],
        ts=body['message']['ts'],
        text="Quote Denied",
        blocks=[{
            "type": "section",
            "text": {
                "type": "mrkdwn", 
                "text": f"❌ *Denied by <@{body['user']['id']}>*"
            }
        }]
    )

# --- APP RUNNER ---
if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_job(set_status, 'cron', hour=9, minute=0)
    scheduler.start()
    
    print("⚡️ StatusQuo is running!")
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
