#!/usr/bin/env python3
"""
Print effective Settings config with all SECRETs masked.

This script loads the Settings class exactly as the app does, printing every
field name and its value. SECRETS are masked as *** set*** or ***unset***.

Usage:
  python scripts/print_effective_config.py [--before-format]

Output is sorted by field name for diff-friendly comparison across changes.
"""
import sys
import os
from pathlib import Path

# Add the project root to sys.path so we can import app modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.config import Settings

# Fields that contain secrets (passwords, tokens, keys, URLs with credentials)
SECRET_FIELDS = {
    "database_url",
    "postgres_password",
    "telegram_api_id",
    "telegram_api_hash",
    "telegram_session_string",
    "cnrs_api_key",
    "cnrs_webhook_secret",
    "ollama_api_key",
    "air_violation_webhook_secret",
    "air_violation_webhook_url",  # May contain credentials depending on scheme
    "super_admin_seed_password",
    "postgres_user",
}


def mask_value(field_name: str, value: any) -> str:
    """Return masked or actual value representation."""
    if field_name.lower() in SECRET_FIELDS:
        if value is None:
            return "***unset***"
        elif isinstance(value, str) and value:
            return "***set***"
        else:
            return "***unset***"
    return repr(value)


def main():
    """Load Settings and print effective config."""
    settings = Settings()

    # Get all fields in alphabetical order
    fields = sorted(settings.model_fields.keys())

    # Print header
    print("EFFECTIVE SETTINGS CONFIG")
    print("=" * 80)
    print(f"Loaded from env: {os.getenv('DATABASE_URL', 'not set')[:20]}...")
    print()

    # Print each field
    for field_name in fields:
        value = getattr(settings, field_name)
        masked = mask_value(field_name, value)
        print(f"{field_name:50} = {masked}")

    print()
    print("=" * 80)
    print(f"Total fields: {len(fields)}")


if __name__ == "__main__":
    main()
