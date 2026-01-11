import os
import json
import logging
import boto3
from slack_sdk.oauth.installation_store import InstallationStore, Installation

class DynamoDBInstallationStore(InstallationStore):
    def __init__(self, table_name='SlackInstallations', client_id=None):
        self.client_id = client_id or os.environ.get("SLACK_CLIENT_ID")
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(table_name)

    def save(self, installation: Installation):
        """Saves an installation to DynamoDB."""
        try:
            item = {
                'client_id': self.client_id,
                'enterprise_or_team_id': installation.team_id,
                'installation_data': json.dumps(installation.to_dict())
            }
            self.table.put_item(Item=item)
        except Exception as e:
            logging.error(f"Failed to save installation to DynamoDB: {e}")
            raise e

    def find_installation(self, enterprise_id, team_id, user_id=None, is_enterprise_install=False):
        """Retrieves a specific installation by Team ID."""
        try:
            response = self.table.get_item(
                Key={
                    'client_id': self.client_id,
                    'enterprise_or_team_id': team_id
                }
            )
            if 'Item' in response:
                data = json.loads(response['Item']['installation_data'])
                return Installation(**data)
        except Exception as e:
            logging.error(f"Find installation error: {e}")
        return None

    def get_all_installations(self):
        """
        Scans the table and returns a list of Installation objects.
        Used by the scheduler to update status for everyone.
        """
        installations = []
        try:
            # Note: Scan is expensive at scale. For production with 1000+ teams, 
            # consider using a Global Secondary Index (GSI) or parallel scans.
            response = self.table.scan()
            items = response.get('Items', [])
            
            for item in items:
                try:
                    data = json.loads(item['installation_data'])
                    installations.append(Installation(**data))
                except Exception as parse_error:
                    logging.error(f"Skipping invalid record: {parse_error}")
                    
        except Exception as e:
            logging.error(f"Error scanning installations: {e}")
            
        return installations
