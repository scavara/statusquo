import sys
import os
import uuid
import csv
import boto3
from dotenv import load_dotenv
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError

# --- Main Logic ---
load_dotenv()


def get_dynamodb_resource():
    try:
        return boto3.resource("dynamodb")
    except (NoCredentialsError, PartialCredentialsError):
        print("Error: AWS credentials not found. Check your .env file.")
        sys.exit(1)


def get_existing_quotes(table):
    print("Scanning table for existing quotes to prevent duplicates...")
    existing_texts = set()
    try:
        response = table.scan(
            ProjectionExpression="#t", ExpressionAttributeNames={"#t": "text"}
        )
        data = response.get("Items", [])

        for item in data:
            if "text" in item:
                existing_texts.add(item["text"])

        while "LastEvaluatedKey" in response:
            response = table.scan(
                ProjectionExpression="#t",
                ExpressionAttributeNames={"#t": "text"},
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            data = response.get("Items", [])
            for item in data:
                if "text" in item:
                    existing_texts.add(item["text"])

    except ClientError as e:
        print(f"Warning: Could not scan table. Duplicates might be created. Error: {e}")

    print(f"Found {len(existing_texts)} existing quotes in database.")
    return existing_texts


def import_csv_to_dynamodb(csv_filepath, table_name):
    if not os.path.exists(csv_filepath):
        print(f"Error: File '{csv_filepath}' not found.")
        return

    dynamodb = get_dynamodb_resource()
    table = dynamodb.Table(table_name)

    existing_quotes = get_existing_quotes(table)

    print(f"Reading {csv_filepath} into table '{table_name}'...")

    try:
        imported_count = 0
        skipped_dup_count = 0
        skipped_len_count = 0

        with open(csv_filepath, mode="r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            with table.batch_writer() as batch:
                for row in reader:
                    # Clean up fields
                    text_clean = row["text"].strip('"').strip()
                    author_clean = row["author"].strip('"').strip()
                    emoji_clean = row["emoji"].strip('"').strip()

                    # Check Length
                    total_length = (
                        len(text_clean) + len(author_clean) + len(emoji_clean)
                    )
                    if total_length > 100:
                        print(
                            f"⚠️  Skipping (Too long: {total_length} chars): {text_clean[:30]}..."
                        )
                        skipped_len_count += 1
                        continue

                    # Check Duplicates
                    if text_clean in existing_quotes:
                        print(f"⚠️  Skipping (Duplicate): {text_clean[:30]}...")
                        skipped_dup_count += 1
                        continue

                    generated_id = str(uuid.uuid4())
                    item = {
                        "quote_id": generated_id,
                        "author": author_clean,
                        "emoji": emoji_clean,
                        "text": text_clean,
                    }

                    batch.put_item(Item=item)
                    existing_quotes.add(text_clean)
                    imported_count += 1

        print("-" * 40)
        print(f"✅ Import Complete!")
        print(f"   - Imported: {imported_count}")
        print(f"   - Skipped (Duplicates): {skipped_dup_count}")
        print(f"   - Skipped (Too Long): {skipped_len_count}")

    except KeyError as e:
        print(f"❌ CSV Error: Missing column {e}. Expecting: author, emoji, text")
    except Exception as e:
        print(f"❌ Error: {str(e)}")


if __name__ == "__main__":
    # Ensure this matches your actual table name in AWS
    import_csv_to_dynamodb("quotes.csv", "FunQuotes")
