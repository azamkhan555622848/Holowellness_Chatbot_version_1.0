import boto3
import os

S3_BUCKET = "holowellness"
DEST_DIR = os.path.join(os.path.dirname(__file__), "pdfs")  # Backend's pdfs folder
AWS_ACCESS_KEY_ID = "AKIA6JKEX4LUK6MIRW7H"
AWS_SECRET_ACCESS_KEY = "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"
REGION = "ap-northeast-3"

s3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=REGION,
)

def sync_pdfs_from_s3():
    os.makedirs(DEST_DIR, exist_ok=True)
    s3_files = set()
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="rag_pdfs/"):
        for obj in page.get('Contents', []):
            key = obj['Key']
            if not key.lower().endswith('.pdf'):
                continue
            filename = os.path.basename(key)
            s3_files.add(filename)
            dest_path = os.path.join(DEST_DIR, filename)
            if not os.path.exists(dest_path) or os.path.getsize(dest_path) != obj['Size']:
                print(f"Downloading {key} to {dest_path}")
                s3.download_file(S3_BUCKET, key, dest_path)
    # Delete local PDFs not in S3
    local_files = {f for f in os.listdir(DEST_DIR) if f.lower().endswith('.pdf')}
    files_to_delete = local_files - s3_files
    for filename in files_to_delete:
        local_path = os.path.join(DEST_DIR, filename)
        print(f"Deleting local file not in S3: {filename}")
        os.remove(local_path)

    # --- ADD THESE LINES BELOW ---
    # Delete rag_cache.pkl to force fresh re-indexing next run
    cache_file = os.path.join(DEST_DIR, "rag_cache.pkl")
    if os.path.exists(cache_file):
        print("Deleting old cache file to force re-indexing.")
        os.remove(cache_file)

if __name__ == "__main__":
    print("Syncing PDFs from S3...")
    sync_pdfs_from_s3()
    print("Done! All PDFs are synced to the 'pdfs' folder.")
