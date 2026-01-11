import boto3
import logging

class FilterStore:
    def __init__(self, table_name='UserFilters'):
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(table_name)

    def set_filter(self, user_id, author_name):
        try:
            self.table.put_item(Item={'user_id': user_id, 'author_filter': author_name})
            return True
        except Exception as e:
            logging.error(f"Error setting filter: {e}")
            return False

    def get_filter(self, user_id):
        try:
            response = self.table.get_item(Key={'user_id': user_id})
            return response.get('Item', {}).get('author_filter')
        except Exception as e:
            logging.error(f"Error getting filter: {e}")
            return None

    def clear_filter(self, user_id):
        try:
            self.table.delete_item(Key={'user_id': user_id})
            return True
        except Exception as e:
            logging.error(f"Error clearing filter: {e}")
            return False
