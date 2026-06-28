"""
S3 Helper

Utility functions to interact with **AWS S3 and any S3-compatible
object storage**: upload, download, list, exists, remove, plus a
``remote_tempfile`` context manager that gives you a unique key and
cleans up automatically.

Backed by :mod:`boto3`. SSL certificate verification is on by default
and never disabled silently — callers may opt out per-call via
``cred["s3_verify_ssl"] = false`` only if they really mean it (handy
for a self-signed MinIO behind a corporate VPN).

S3-compatible endpoints
-----------------------
Anything that speaks the AWS S3 API works transparently — just set
``cred["s3_endpoint_url"]`` to the endpoint:

- **AWS S3** : leave ``s3_endpoint_url`` empty or unset (boto3 picks
  ``s3.<region>.amazonaws.com`` automatically).
- **MinIO** : ``"http://minio.example.com:9000"`` or ``"https://minio.example.com"``.
- **DigitalOcean Spaces** : ``"https://nyc3.digitaloceanspaces.com"``.
- **Cloudflare R2** : ``"https://<account_id>.r2.cloudflarestorage.com"``.
- **Backblaze B2** (S3 API) : ``"https://s3.us-west-001.backblazeb2.com"``.
- **Wasabi** : ``"https://s3.us-east-1.wasabisys.com"``.

Author:
- Warith HARCHAOUI (https://harchaoui.org/warith)
"""

import logging
import os
import secrets
from contextlib import contextmanager
from typing import Iterator, List, Optional, Tuple
from urllib.parse import urlparse

import boto3
import botocore.exceptions
import os_helper as osh


# ---------------------------------------------------------------------------
# Credentials loader
# ---------------------------------------------------------------------------


def credentials(config_path: Optional[str] = None) -> dict:
    """
    Retrieve S3 credentials from a configuration file, folder, or environment.

    Loads (in this precedence order) from JSON / YAML files, ``.env``, then
    environment variables — see :func:`os_helper.get_config`.

    Required keys
    -------------
    - ``s3_access_key`` : your access key ID
    - ``s3_secret_key`` : your secret access key
    - ``s3_bucket``     : default bucket name
    - ``s3_https``      : base public URL for built objects, e.g.
      ``"https://my-bucket.s3.eu-west-3.amazonaws.com"`` or
      ``"https://cdn.example.com"`` (used by ``remote_tempfile`` to build
      the public URL handed back to the caller)

    Optional keys
    -------------
    - ``s3_region``       : AWS region (defaults to ``"us-east-1"`` if absent,
      mostly irrelevant for path-style MinIO etc.)
    - ``s3_endpoint_url`` : custom endpoint for S3-compatible storage
      (MinIO, R2, B2, Spaces, Wasabi). Empty / missing → AWS S3.
    - ``s3_prefix``       : default key prefix (path-like, e.g. ``"uploads"``)
    - ``s3_use_path_style`` : ``"true"`` to force path-style addressing
      (typical for MinIO with custom domains). Default ``"false"`` (uses
      virtual-hosted style).
    - ``s3_verify_ssl``   : ``"false"`` to disable TLS verification (use
      sparingly — e.g. dev MinIO with self-signed cert).

    Returns
    -------
    dict
        Credentials dict.
    """
    required = ["s3_access_key", "s3_secret_key", "s3_bucket", "s3_https"]
    cred = osh.get_config(required, "S3", config_path)
    # Pick up optional keys best-effort from the environment so the bucket /
    # MinIO endpoint can be configured the same way as the required keys
    # without having to reach into os.environ from the caller.
    for opt in (
        "s3_region", "s3_endpoint_url", "s3_prefix",
        "s3_use_path_style", "s3_verify_ssl",
    ):
        if opt in cred:
            continue
        env_val = os.environ.get(opt.upper()) or os.environ.get(opt)
        if env_val is not None:
            cred[opt] = env_val
    return cred


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def _truthy(value: object) -> bool:
    """Lenient bool parser for string-valued config flags."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@contextmanager
def get_client_s3(cred: dict) -> Iterator["boto3.client"]:
    """
    Open a boto3 S3 client honoring ``cred`` configuration.

    The client is configured per AWS S3 (no ``endpoint_url``) or per the
    S3-compatible endpoint when ``cred["s3_endpoint_url"]`` is set.

    Yields
    ------
    boto3.client
        Ready-to-use S3 client.
    """
    endpoint_url = cred.get("s3_endpoint_url")
    if osh.emptystring(endpoint_url):
        endpoint_url = None

    region = cred.get("s3_region") or "us-east-1"

    use_path_style = _truthy(cred.get("s3_use_path_style"))
    addressing_style = "path" if use_path_style else "auto"

    verify_ssl = True
    if "s3_verify_ssl" in cred and not _truthy(cred.get("s3_verify_ssl")):
        verify_ssl = False

    config = boto3.session.Config(
        signature_version="s3v4",
        s3={"addressing_style": addressing_style},
        retries={"max_attempts": 5, "mode": "standard"},
    )

    client = boto3.client(
        "s3",
        aws_access_key_id=cred["s3_access_key"],
        aws_secret_access_key=cred["s3_secret_key"],
        region_name=region,
        endpoint_url=endpoint_url,
        verify=verify_ssl,
        config=config,
    )

    try:
        yield client
    finally:
        # boto3 clients are stateless wrt connections, but close the
        # underlying urllib3 pool to be tidy.
        try:
            client.close()
        except Exception:  # pragma: no cover — boto3 quirk on some versions
            pass


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------


def _split_s3_address(s3_address: str, default_bucket: str) -> Tuple[str, str]:
    """Normalise ``s3_address`` into ``(bucket, key)``.

    Accepted forms:
    - ``"s3://bucket/path/to/object"`` → ``("bucket", "path/to/object")``
    - ``"path/to/object"`` (no scheme) → ``(default_bucket, "path/to/object")``
    """
    if s3_address.startswith("s3://"):
        parsed = urlparse(s3_address)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"Malformed s3:// URI: {s3_address!r}")
        return bucket, key
    return default_bucket, s3_address.lstrip("/")


def _build_public_url(cred: dict, key: str) -> str:
    """Compose ``cred["s3_https"] + "/" + key`` cleanly."""
    base = cred["s3_https"].rstrip("/")
    return f"{base}/{key.lstrip('/')}"


def strip_s3_path(s3_address: str, cred: dict) -> str:
    """Return the key part of ``s3_address`` (compat with sftp-helper's
    ``strip_sftp_path``)."""
    _, key = _split_s3_address(s3_address, cred["s3_bucket"])
    return key


# ---------------------------------------------------------------------------
# Core CRUD
# ---------------------------------------------------------------------------


def exists(s3_address: str, cred: dict) -> bool:
    """Return True if the object at ``s3_address`` exists, False otherwise."""
    bucket, key = _split_s3_address(s3_address, cred["s3_bucket"])
    with get_client_s3(cred) as s3:
        try:
            s3.head_object(Bucket=bucket, Key=key)
            return True
        except botocore.exceptions.ClientError as err:
            code = err.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise


def upload(local_path: str, cred: dict, s3_address: str = "", content_type: Optional[str] = None) -> str:
    """
    Upload a local file to S3.

    Parameters
    ----------
    local_path : str
        Path to the local file.
    cred : dict
        Credentials dict from :func:`credentials`.
    s3_address : str, optional
        Destination — either ``"s3://bucket/key"`` or a key under the
        default bucket. If empty, a content-hashed name is generated
        under ``cred["s3_prefix"]`` (if set) of the default bucket.
    content_type : str, optional
        Override the MIME ``Content-Type`` header. If None, boto3 lets the
        server default (typically ``application/octet-stream``).

    Returns
    -------
    str
        The full ``s3://bucket/key`` URI of the uploaded object.

    Raises
    ------
    botocore.exceptions.ClientError
        If the upload fails (permissions, bucket missing, network).
    AssertionError
        If ``local_path`` does not exist or is empty.
    """
    osh.checkfile(local_path, msg=f"Local file not found / empty: {local_path}", check_empty=True)

    if osh.emptystring(s3_address):
        _, _, ext = osh.folder_name_ext(local_path)
        prefix = cred.get("s3_prefix")
        prefix = "" if osh.emptystring(prefix) else prefix.strip("/") + "/"
        name = secrets.token_hex(16)
        if not osh.emptystring(ext):
            name = f"{name}.{ext.lstrip('.')}"
        s3_address = f"{prefix}{name}"

    bucket, key = _split_s3_address(s3_address, cred["s3_bucket"])

    extra_args: dict = {}
    if content_type is not None:
        extra_args["ContentType"] = content_type

    with get_client_s3(cred) as s3:
        s3.upload_file(local_path, bucket, key, ExtraArgs=extra_args or None)

    uri = f"s3://{bucket}/{key}"
    logging.info("S3 upload OK: %s → %s", local_path, uri)
    return uri


def download(s3_address: str, local_path: str, cred: dict) -> str:
    """
    Download an S3 object to a local path. Returns ``local_path`` on success.
    """
    bucket, key = _split_s3_address(s3_address, cred["s3_bucket"])

    parent = os.path.dirname(local_path)
    if parent:
        osh.make_directory(parent)

    with get_client_s3(cred) as s3:
        s3.download_file(bucket, key, local_path)

    osh.checkfile(local_path, msg=f"Download failed (file missing or empty): {local_path}", check_empty=True)
    logging.info("S3 download OK: s3://%s/%s → %s", bucket, key, local_path)
    return local_path


def delete(s3_address: str, cred: dict) -> bool:
    """
    Delete an S3 object. Returns True if the object is gone after the call
    (including the case where it never existed — S3's delete is idempotent).
    """
    bucket, key = _split_s3_address(s3_address, cred["s3_bucket"])
    with get_client_s3(cred) as s3:
        try:
            s3.delete_object(Bucket=bucket, Key=key)
        except botocore.exceptions.ClientError as err:
            raise RuntimeError(
                f"Failed to delete S3 object s3://{bucket}/{key}: {err}"
            ) from err
    logging.info("S3 delete OK: s3://%s/%s", bucket, key)
    return True


def list_prefix(prefix: str, cred: dict, *, max_keys: int = 1000) -> List[str]:
    """
    List the object keys under ``prefix`` in the default bucket.

    Returns at most ``max_keys`` keys, ordered by S3's lexicographic
    response (no client-side sort). For very large prefixes, paginate
    via boto3 directly with ``get_client_s3``.
    """
    bucket = cred["s3_bucket"]
    keys: List[str] = []
    with get_client_s3(cred) as s3:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=bucket,
            Prefix=prefix.lstrip("/"),
            PaginationConfig={"MaxItems": max_keys},
        ):
            for obj in page.get("Contents") or []:
                keys.append(obj["Key"])
                if len(keys) >= max_keys:
                    return keys
    return keys


def make_bucket(bucket: str, cred: dict) -> None:
    """Create a bucket if it doesn't exist.

    Honors ``cred["s3_region"]`` for the LocationConstraint. No-op when
    the bucket already exists and is owned by the credentials.
    """
    region = cred.get("s3_region") or "us-east-1"
    with get_client_s3(cred) as s3:
        try:
            if region == "us-east-1":
                # us-east-1 must NOT have a LocationConstraint — AWS quirk.
                s3.create_bucket(Bucket=bucket)
            else:
                s3.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={"LocationConstraint": region},
                )
            logging.info("S3 bucket created: %s (region=%s)", bucket, region)
        except botocore.exceptions.ClientError as err:
            code = err.response.get("Error", {}).get("Code", "")
            if code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                logging.info("S3 bucket already exists: %s", bucket)
                return
            raise


# ---------------------------------------------------------------------------
# remote_tempfile — unique key, auto-cleanup
# ---------------------------------------------------------------------------


@contextmanager
def remote_tempfile(
    cred: dict,
    *,
    ext: str = "",
    prefix: str = "",
) -> Iterator[Tuple[str, str]]:
    """
    Yield ``(s3_address, public_url)`` for a unique key, deleted on exit.

    Useful for stage-and-share flows: upload a generated file, hand the
    public URL to whoever needs it (a downstream worker, a webhook
    target, a test fixture), and let the context manager clean up the
    remote artifact at the end of the block — even on exception.

    Parameters
    ----------
    cred : dict
        Credentials dict from :func:`credentials`. The object goes under
        ``cred["s3_bucket"]``; the public URL is built from
        ``cred["s3_https"]``.
    ext : str, optional
        Extension to append to the random name (with or without leading
        ``.``). Default empty.
    prefix : str, optional
        Extra path segment under the bucket / default prefix. Default empty.

    Yields
    ------
    (s3_address, public_url) : tuple of str
        ``s3_address`` is ``"s3://bucket/key"``; ``public_url`` is the
        ``https://...`` URL built from ``cred["s3_https"]``.

    Example
    -------
    >>> import s3_helper as s3h
    >>> cred = s3h.credentials("path/to/s3_config.json")
    >>> with s3h.remote_tempfile(cred, ext="json") as (addr, url):
    ...     s3h.upload("payload.json", cred, addr, content_type="application/json")
    ...     # publish `url` somewhere, e.g. trigger a webhook
    >>> # the object is gone after the block — even if the body raised.
    """
    name = secrets.token_hex(16)
    if not osh.emptystring(ext):
        name = f"{name}.{ext.lstrip('.')}"

    base_prefix = cred.get("s3_prefix")
    base_prefix = "" if osh.emptystring(base_prefix) else base_prefix.strip("/")
    if not osh.emptystring(prefix):
        clean = prefix.strip("/")
        base_prefix = f"{base_prefix}/{clean}" if base_prefix else clean

    key = f"{base_prefix}/{name}" if base_prefix else name
    bucket = cred["s3_bucket"]
    s3_address = f"s3://{bucket}/{key}"
    public_url = _build_public_url(cred, key)

    try:
        yield s3_address, public_url
    finally:
        # Best-effort cleanup; never re-raise so the caller's original
        # exception (if any) wins.
        try:
            delete(s3_address, cred)
        except Exception as err:  # pragma: no cover
            logging.warning("S3 remote_tempfile cleanup failed for %s: %s", s3_address, err)
