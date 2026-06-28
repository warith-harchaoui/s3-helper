# -*- coding: utf-8 -*-
"""setuptools shim — actual configuration lives in pyproject.toml."""
from pathlib import Path

from setuptools import setup

long_description = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")

setup(
    name="s3-helper",
    version="0.1.0",
    description=(
        "S3 Helper: utility functions for AWS S3 and any S3-compatible "
        "object storage (MinIO, Backblaze B2 S3, DigitalOcean Spaces, "
        "Cloudflare R2, Wasabi, etc.) via boto3."
    ),
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Warith HARCHAOUI",
    author_email="Warith HARCHAOUI <warithmetics@deraison.ai>",
    url="https://github.com/warith-harchaoui/s3-helper",
    packages=["s3_helper"],
    package_data={"": ["*"]},
    install_requires=[
        "boto3>=1.34,<2",
        "botocore>=1.34,<2",
        "os-helper @ git+https://github.com/warith-harchaoui/os-helper.git@v1.3.0",
    ],
    extras_require={
        "dev": ["pytest>=7", "pyyaml>=6", "moto[s3]>=5"],
    },
    python_requires=">=3.10,<3.14",
)
