import os
import json
import logging
import boto3
import time
import uuid
from slack_sdk.oauth.installation_store import InstallationStore, Installation
from slack_sdk.oauth.state_store import OAuthStateStore

# --- 1. Installation Store (Saves tokens) ---
class DynamoDBInstallationStore(InstallationStore):
    def __init__(self, table_name="SlackInstallations", client_id=None, logger=None):
        self.client_id = client_id or os.environ.get("SLACK_CLIENT_ID")
        self.dynamodb = boto3.resource("dynamodb")
        self.table = self.dynamodb.Table(table_name)
        self._logger = logger or logging.getLogger(__name__)

    @property
    def logger(self):
        return self._logger

    def save(self, installation: Installation):
        """Saves an installation to DynamoDB."""
        try:
            item = {
                "client_id": self.client_id,
                "enterprise_or_team_id": installation.team_id,
                "installation_data": json.dumps(installation.to_dict(), default=str),
            }
            self.table.put_item(Item=item)
        except Exception as e:
            self.logger.error(f"Failed to save installation to DynamoDB: {e}")
            raise e

    def find_installation(
        self, enterprise_id, team_id, user_id=None, is_enterprise_install=False
    ):
        """Retrieves a specific installation by Team ID."""
        try:
            response = self.table.get_item(
                Key={"client_id": self.client_id, "enterprise_or_team_id": team_id}
            )
            if "Item" in response:
                data = json.loads(response["Item"]["installation_data"])
                return Installation(**data)
        except Exception as e:
            self.logger.error(f"Find installation error: {e}")
        return None

    def get_all_installations(self):
        """
        Scans the table and returns a list of Installation objects.
        Used by the scheduler to update status for everyone.
        """
        installations = []
        try:
            response = self.table.scan()
            items = response.get("Items", [])

            for item in items:
                try:
                    data = json.loads(item["installation_data"])
                    installations.append(Installation(**data))
                except Exception as parse_error:
                    self.logger.error(f"Skipping invalid record: {parse_error}")

        except Exception as e:
            self.logger.error(f"Error scanning installations: {e}")

        return installations


# --- 2. OAuth State Store (Saves login state for Security) ---
class DynamoDBOAuthStateStore(OAuthStateStore):
    def __init__(self, table_name="SlackOAuthState", expiration_seconds=600, logger=None):
        self.dynamodb = boto3.resource("dynamodb")
        self.table = self.dynamodb.Table(table_name)
        self.expiration_seconds = expiration_seconds
        # FIX: Use _logger instead of self.logger
        self._logger = logger or logging.getLogger(__name__)

    @property
    def logger(self):
        return self._logger

    def issue(self, *args, **kwargs) -> str:
        state = str(uuid.uuid4())
        expire_at = int(time.time()) + self.expiration_seconds
        try:
            self.table.put_item(Item={"state": state, "expire_at": expire_at})
            return state
        except Exception as e:
            self.logger.error(f"Failed to issue state: {e}")
            raise e

    def consume(self, state: str) -> bool:
        try:
            response = self.table.get_item(Key={"state": state})
            item = response.get("Item")
            if not item:
                return False

            # Delete the state (consume it) so it can't be reused
            self.table.delete_item(Key={"state": state})

            # Check expiration
            current_ts = int(time.time())
            return current_ts < int(item["expire_at"])
        except Exception as e:
            self.logger.error(f"Failed to consume state: {e}")
            return False
