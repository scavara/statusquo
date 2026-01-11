import subprocess
import sys
import os
import uuid 
import csv
import boto3
from dotenv import load_dotenv
from botocore.exceptions import NoCredentialsError, PartialCredentialsError

# --- 1. Dependencies ---
def install_dependencies():
    required_packages = ['boto3', 'python-dotenv']
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + required_packages)
    except subprocess.CalledProcessError:
        print("Failed to install required packages.")
        sys.exit(1)

install_dependencies()

# --- 2. Main Logic ---
load_dotenv()

def get_dynamodb_resource():
    try:
        return boto3.resource('dynamodb')
    except (NoCredentialsError, PartialCredentialsError):
        print("Error: AWS credentials not found. Check your .env file.")
        sys.exit(1)

def import_csv_to_dynamodb(csv_filepath, table_name):
    if not os.path.exists(csv_filepath):
        print(f"Error: File '{csv_filepath}' not found.")
        return

    dynamodb = get_dynamodb_resource()
    table = dynamodb.Table(table_name)
    
    print(f"Reading {csv_filepath} into table '{table_name}'...")

    try:
        row_count = 0
        with open(csv_filepath, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            with table.batch_writer() as batch:
                for row in reader:
                    generated_id = str(uuid.uuid4())

                    # --- THE FIX ---
                    # simply strip quote marks from the start/end
                    clean_text = row['text'].strip('"')

                    item = {
                        'quote_id': generated_id,
                        'author': row['author'],
                        'emoji': row['emoji'],
                        'text': clean_text
                    }
                    
                    batch.put_item(Item=item)
                    row_count += 1
                    
        print(f"✅ Success! Imported {row_count} quotes (cleaned of extra quotes).")

    except KeyError as e:
        print(f"❌ CSV Error: Missing column {e}. Expecting: author, emoji, text")
    except Exception as e:
        print(f"❌ Error: {str(e)}")

if __name__ == "__main__":
    import_csv_to_dynamodb('quotes.csv', 'FunQuotes')
