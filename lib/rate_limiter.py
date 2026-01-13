import time
import datetime
from botocore.exceptions import ClientError


class RateLimiter:
    def __init__(self, table):
        self.table = table

    def _get_user_stats(self, user_id):
        """Fetches the rate limit record for a user."""
        try:
            response = self.table.get_item(Key={"quote_id": f"USER_{user_id}"})
            return response.get("Item", {})
        except ClientError:
            return {}

    # --- FEATURE 1: UPDATE STATUS LIMIT (1 per 10m) ---
    def check_update_limit(self, user_id, limit_minutes=10):
        stats = self._get_user_stats(user_id)
        last_ts = int(stats.get("last_update_ts", 0))
        current_ts = int(time.time())

        diff = current_ts - last_ts
        limit_seconds = limit_minutes * 60

        if diff < limit_seconds:
            wait_time = int((limit_seconds - diff) / 60) + 1
            return (
                False,
                f"⏳ *Cooldown Active:* Please wait {wait_time} minutes before updating your status again.",
            )

        return True, None

    def log_update_attempt(self, user_id):
        """Updates the timestamp to NOW."""
        self.table.update_item(
            Key={"quote_id": f"USER_{user_id}"},
            UpdateExpression="SET last_update_ts = :ts",
            ExpressionAttributeValues={":ts": int(time.time())},
        )

    # --- FEATURE 2: ADD QUOTE LIMITS ---
    def check_add_limit(self, user_id, max_pending=3, max_daily=10):
        stats = self._get_user_stats(user_id)

        # 1. Reset Daily Count if it's a new day
        last_date = stats.get("last_activity_date", "")
        today = datetime.datetime.now().strftime("%Y-%m-%d")

        daily_count = int(stats.get("daily_approved_count", 0))
        pending_count = int(stats.get("pending_count", 0))

        # Safety: If pending count is stuck but user hasn't touched it in 24h, reset it
        last_ts = int(stats.get("last_submission_ts", 0))
        if (int(time.time()) - last_ts) > 86400:
            pending_count = 0

        if last_date != today:
            daily_count = 0  # New day, new quota
            # We don't save this reset yet, we assume it during the check

        # 2. Check Limits
        if pending_count >= max_pending:
            return (
                False,
                f"🛑 *Limit Reached:* You have {pending_count} pending quotes. Please wait for approval/denial before adding more.",
            )

        if daily_count >= max_daily:
            return (
                False,
                f"🛑 *Daily Quota:* You've added {daily_count} approved quotes today. Try again tomorrow!",
            )

        return True, None

    def increment_pending(self, user_id):
        """User just requested a new quote."""
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        current_ts = int(time.time())

        self.table.update_item(
            Key={"quote_id": f"USER_{user_id}"},
            UpdateExpression="SET pending_count = if_not_exists(pending_count, :zero) + :inc, last_activity_date = :today, last_submission_ts = :ts",
            ExpressionAttributeValues={
                ":inc": 1,
                ":zero": 0,
                ":today": today,
                ":ts": current_ts,
            },
        )

    def process_approval(self, user_id):
        """Quote Approved: Pending -1, Approved +1"""
        # We also handle the daily reset logic here implicitly by just incrementing
        # (Real-world app might need stricter date handling, but this suffices for a bot)
        self.table.update_item(
            Key={"quote_id": f"USER_{user_id}"},
            UpdateExpression="SET pending_count = pending_count - :dec, daily_approved_count = if_not_exists(daily_approved_count, :zero) + :inc",
            ExpressionAttributeValues={":dec": 1, ":inc": 1, ":zero": 0},
        )

    def process_denial(self, user_id):
        """Quote Denied: Pending -1"""
        self.table.update_item(
            Key={"quote_id": f"USER_{user_id}"},
            UpdateExpression="SET pending_count = pending_count - :dec",
            ExpressionAttributeValues={":dec": 1},
        )
