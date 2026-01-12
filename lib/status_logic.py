import time
import random
import logging
from boto3.dynamodb.conditions import Key, Attr
from slack_sdk.errors import SlackApiError  # Import Slack Error handling

# Setup Logger
logger = logging.getLogger(__name__)


def get_quote_for_user(user_id, filter_store, quotes_table):
    """
    Finds the perfect quote for a user:
    1. Checks their filter.
    2. Scans for PARTIAL match (e.g. 'Twain' finds 'Mark Twain').
    3. Falls back to random.
    """
    # 1. Check Filter
    author_filter = filter_store.get_filter(user_id)

    if author_filter:
        try:
            # 2. SCAN with CONTAINS (Partial Match)
            # Note: This is case-sensitive ("futurama" won't match "Futurama").
            response = quotes_table.scan(
                FilterExpression=Attr("author").contains(author_filter)
            )
            items = response.get("Items", [])

            if items:
                return random.choice(items)
            else:
                logger.warning(
                    f"Filter '{author_filter}' found no matches. Falling back."
                )
        except Exception as e:
            logger.error(f"Filter scan failed: {e}")

    # 3. Fallback: Random Scan
    try:
        response = quotes_table.scan()
        items = response.get("Items", [])
        if items:
            return random.choice(items)
    except Exception as e:
        logger.error(f"Scan failed: {e}")

    return {"text": "No quotes available", "author": "System", "emoji": ":x:"}


def perform_user_update(installation, client, filter_store, quotes_table):
    """
    Performs the actual API call to Slack to update status.
    Handles 'invalid_emoji' errors by retrying with a default.
    """
    try:
        user_id = installation.user_id

        # 1. Get the quote
        quote = get_quote_for_user(user_id, filter_store, quotes_table)

        # 2. Format Text
        author = quote.get("author", "Anonymous")
        text = f'"{quote["text"]}." --{author}'

        if len(text) > 100:
            text = text[:97] + "..."

        # 3. Get Raw Emoji (Basic cleanup only)
        emoji = quote.get("emoji", "").strip()
        if not emoji:
            emoji = ":speech_balloon:"

        # 4. Attempt Update (FAIL-SAFE LOGIC)
        try:
            client.users_profile_set(
                token=installation.user_token,
                profile={
                    "status_text": text,
                    "status_emoji": emoji,
                    "status_expiration": 0,
                },
            )
        except SlackApiError as slack_err:
            # Check if the specific error is about the emoji
            error_code = slack_err.response.get("error")

            if error_code == "profile_status_set_failed_not_valid_emoji":
                logger.warning(
                    f"⚠️ Invalid emoji '{emoji}' for user {user_id}. Retrying with default."
                )

                # RETRY with safe default
                client.users_profile_set(
                    token=installation.user_token,
                    profile={
                        "status_text": text,
                        "status_emoji": ":speech_balloon:",  # Guaranteed to work
                        "status_expiration": 0,
                    },
                )
            else:
                # If it's a different error (like auth failed), raise it so the outer loop catches it
                raise slack_err

        return True, text

    except Exception as e:
        logger.error(f"Error updating user {installation.user_id}: {e}")
        return False, str(e)
