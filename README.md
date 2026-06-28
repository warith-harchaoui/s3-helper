# S3 Helper

`S3 Helper` belongs to a collection of libraries called `AI Helpers` developed for building Artificial Intelligence.

Utility functions for **AWS S3** and any **S3-compatible object storage** — MinIO, Backblaze B2 S3 API, DigitalOcean Spaces, Cloudflare R2, Wasabi, and friends. Built on [boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html). Same shape as [sftp-helper](https://github.com/warith-harchaoui/sftp-helper): a `credentials()` loader, the usual CRUD (`upload` / `download` / `delete` / `exists` / `list_prefix`), and a `remote_tempfile` context manager for stage-and-share flows.

[🕸️ AI Helpers](https://harchaoui.org/warith/ai-helpers)

# Installation

```bash
pip install --force-reinstall --no-cache-dir git+https://github.com/warith-harchaoui/s3-helper.git@v0.1.0
```

# Configuration

Write a `s3_config.json`, `s3_config.yaml`, `.env`, or use environment variables. Required keys:

```json
{
  "s3_access_key": "AKIA...",
  "s3_secret_key": "...",
  "s3_bucket":     "my-bucket",
  "s3_https":      "https://my-bucket.s3.eu-west-3.amazonaws.com"
}
```

Optional keys:

| Key | Default | Notes |
|---|---|---|
| `s3_region` | `"us-east-1"` | AWS region; mostly cosmetic for MinIO / R2 |
| `s3_endpoint_url` | empty (= AWS S3) | Set this for S3-compatible backends — see table below |
| `s3_prefix` | empty | Default key prefix added by `upload(...)` when no destination is given |
| `s3_use_path_style` | `"false"` | Force path-style addressing (`endpoint/bucket/key` instead of `bucket.endpoint/key`). Typical for MinIO with custom domains. |
| `s3_verify_ssl` | `"true"` | Disable only for dev MinIO with self-signed certs |

## Endpoint URLs for common S3-compatible storage

Set `s3_endpoint_url` to:

| Provider | Endpoint |
|---|---|
| **AWS S3** | leave empty / unset |
| **MinIO** | `http://minio.example.com:9000` (or `https://...` with TLS) |
| **DigitalOcean Spaces** | `https://nyc3.digitaloceanspaces.com` (region in subdomain) |
| **Cloudflare R2** | `https://<account_id>.r2.cloudflarestorage.com` |
| **Backblaze B2 (S3 API)** | `https://s3.<region>.backblazeb2.com` |
| **Wasabi** | `https://s3.<region>.wasabisys.com` |

# Usage

```python
import s3_helper as s3h

# Load creds — JSON / YAML / env / .env (auto-fallback in that order)
cred = s3h.credentials("path/to/s3_config.json")

# Upload a local file
uri = s3h.upload("local.txt", cred, "folder/uploaded.txt")
# uri == "s3://my-bucket/folder/uploaded.txt"

assert s3h.exists(uri, cred)

# Download
s3h.download(uri, "downloaded.txt", cred)

# List
for key in s3h.list_prefix("folder/", cred):
    print(key)

# Delete
s3h.delete(uri, cred)
```

## MinIO example

```python
cred = {
    "s3_access_key":      "minioadmin",
    "s3_secret_key":      "minioadmin",
    "s3_bucket":          "uploads",
    "s3_https":           "http://minio.example.com:9000/uploads",
    "s3_endpoint_url":    "http://minio.example.com:9000",
    "s3_use_path_style":  "true",
    "s3_region":          "us-east-1",  # MinIO accepts any region string
}

s3h.make_bucket("uploads", cred)
s3h.upload("file.bin", cred, "file.bin")
```

## Stage-and-share with `remote_tempfile`

Drop a generated file at a unique random key, hand the public URL to a
downstream worker / webhook, and the object is deleted on block exit
(even if the body raises):

```python
import s3_helper as s3h
import requests

cred = s3h.credentials("path/to/s3_config.json")

with s3h.remote_tempfile(cred, ext="json", prefix="runs") as (s3_addr, public_url):
    s3h.upload("payload.json", cred, s3_addr, content_type="application/json")
    # Hand the URL to something that fetches it once.
    requests.post("https://hook.example.com/process", json={"input_url": public_url}).raise_for_status()
# Object is gone here, no manual cleanup.
```

# Author
 - [Warith HARCHAOUI](https://harchaoui.org/warith)

# Acknowledgements
Special thanks to [Mohamed Chelali](https://mchelali.github.io) and [Bachir Zerroug](https://www.linkedin.com/in/bachirzerroug) for fruitful discussions.
