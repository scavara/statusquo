import logging
from boto3.dynamodb.conditions import Attr

logger = logging.getLogger(__name__)

class QuoteDeduplicator:
    def __init__(self, table):
        self.table = table

    def check_exists(self, text):
        """
        Checks if the quote text exists in the DB (Case Sensitive Exact Match).
        Returns: (Boolean exists, existing_quote_item)
        """
        try:
            # MVP: Scan table for exact text match.
            # (DynamoDB 'Scan' is O(N), but acceptable for <10k items)
            response = self.table.scan(
                FilterExpression=Attr('text').eq(text)
            )
            
            items = response.get('Items', [])
            if len(items) > 0:
                return True, items[0]
            
            return False, None

        except Exception as e:
            logger.error(f"Deduplication check failed: {e}")
            # Fail safe: If DB errors, assume it doesn't exist so we don't block users.
            return False, None
