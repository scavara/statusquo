import time
import random
import logging
from boto3.dynamodb.conditions import Key

# Setup Logger
logger = logging.getLogger(__name__)

def get_quote_for_user(user_id, filter_store, quotes_table):
    """
    Finds the perfect quote for a user:
    1. Checks their filter (UserFilters table).
    2. Queries the GSI (AuthorIndex) if a filter exists.
    3. Falls back to a random quote.
    """
    # 1. Check Filter
    author_filter = filter_store.get_filter(user_id)
    
    if author_filter:
        try:
            # 2. Query GSI
            # We use the 'AuthorIndex' we created in DynamoDB to find specific authors efficiently
            response = quotes_table.query(
                IndexName='AuthorIndex',
                KeyConditionExpression=Key('author').eq(author_filter)
            )
            items = response.get('Items', [])
            if items:
                return random.choice(items)
            else:
                logger.warning(f"Filter '{author_filter}' found no quotes. Falling back to random.")
        except Exception as e:
            logger.error(f"GSI Query failed: {e}")

    # 3. Fallback: Random Scan
    # (Note: For massive scale, implement a 'Count' metadata strategy instead of Scan)
    try:
        response = quotes_table.scan()
        items = response.get('Items', [])
        if items:
            return random.choice(items)
    except Exception as e:
        logger.error(f"Scan failed: {e}")
    
    return {"text": "No quotes available", "author": "System", "emoji": ":x:"}


def perform_user_update(installation, client, filter_store, quotes_table):
    """
    Performs the actual API call to Slack to update status.
    Returns: (True, status_text) if successful, (False, error_message) if failed.
    """
    try:
        user_id = installation.user_id
        
        # 1. Get the quote
        quote = get_quote_for_user(user_id, filter_store, quotes_table)
        
        # 2. Format Text
        author = quote.get('author', 'Anonymous')
        text = f'"{quote["text"]}." --{author}'
        
        # Safety Check: Slack Status has a strict 100-char limit
        if len(text) > 100: 
            # Truncate and add ellipsis to fit logic
            # allowed length = 100 - 3 (for "...")
            text = text[:97] + "..."

        # 3. Sanitize Emoji
        # Slack API throws 'profile_status_set_failed_not_valid_emoji' if format is wrong
        emoji = quote.get('emoji', '').strip()
        
        # Fallback 1: If empty
        if not emoji:
            emoji = ":speech_balloon:"
            
        # Fallback 2: Basic validation (must start/end with colon)
        # If user entered "smile" instead of ":smile:", we revert to default to prevent crash
        if not (emoji.startswith(":") and emoji.endswith(":")):
            emoji = ":speech_balloon:"

        # 4. Call Slack API
        client.users_profile_set(
            token=installation.user_token,
            profile={
                "status_text": text,
                "status_emoji": emoji,
                "status_expiration": 0 # 0 means "don't clear automatically"
            }
        )
        return True, text

    except Exception as e:
        logger.error(f"Error updating user {installation.user_id}: {e}")
        return False, str(e)
