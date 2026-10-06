"""
GJ-Fashion — AWS S3 Storage Helper Service
Handles file uploads to AWS S3 buckets (or local fallback storage).
"""

import os
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger("gjfashion.s3")

# Try importing boto3 if installed
try:
    import boto3
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


def get_s3_client():
    """Build boto3 S3 client if AWS credentials exist."""
    if not HAS_BOTO3:
        logger.warning("boto3 package not installed. Using local storage fallback.")
        return None

    if not settings.AWS_ACCESS_KEY_ID or not settings.AWS_SECRET_ACCESS_KEY:
        logger.info("AWS credentials not configured in environment. Using local storage fallback.")
        return None

    try:
        return boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION
        )
    except Exception as e:
        logger.error(f"Failed to initialize S3 client: {e}")
        return None


async def save_file(file_bytes: bytes, filename: str, folder: str = "uploads") -> str:
    """
    Saves a file to local static directory AND AWS S3 bucket if configured.
    Returns the file URL / path.
    """
    # Always save a local copy in static_files directory for instant local serving
    local_dir = os.path.join("static_files", folder)
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, filename)
    try:
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        logger.info(f"Saved local file copy: {local_path}")
    except Exception as e:
        logger.error(f"Error saving local file copy: {e}")

    # Upload to AWS S3 in background/try-block if credentials exist
    s3 = get_s3_client()
    s3_bucket = settings.S3_BUCKET_NAME

    if s3 and s3_bucket:
        s3_key = f"{folder}/{filename}"
        try:
            s3.put_object(
                Bucket=s3_bucket,
                Key=s3_key,
                Body=file_bytes
            )
            logger.info(f"Successfully synced {filename} to AWS S3 bucket: {s3_bucket}")
        except Exception as e:
            logger.error(f"AWS S3 upload error: {e}")

    # Return local static path to guarantee instant HTTP 200 image serving
    return f"/static/{folder}/{filename}"

