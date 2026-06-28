"""
S3 Helper

Utility functions for AWS S3 and any S3-compatible object storage
(MinIO, Backblaze B2 S3 API, DigitalOcean Spaces, Cloudflare R2,
Wasabi, …) via :mod:`boto3`. Same shape as ``sftp-helper``:
``credentials()`` loader + ``upload`` / ``download`` / ``delete`` /
``exists`` / ``list_prefix`` / ``make_bucket`` + a ``remote_tempfile``
context manager for stage-and-share flows.

Author:
- Warith HARCHAOUI (https://harchaoui.org/warith)
"""

__all__ = [
    "credentials",
    "get_client_s3",
    "upload",
    "download",
    "delete",
    "exists",
    "list_prefix",
    "make_bucket",
    "remote_tempfile",
    "strip_s3_path",
]

from .main import (
    credentials,
    delete,
    download,
    exists,
    get_client_s3,
    list_prefix,
    make_bucket,
    remote_tempfile,
    strip_s3_path,
    upload,
)
