"""
Configuration settings for the AWS platform management and cost management tools.
"""

import os
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# AWS authentication credentials - from environment variables
# Public Cloud
AWS_PROFILE = os.environ.get('AWS_PROFILE', '')

# List of AWS regions to process
REGIONS = [
    'us-east-1',      # US East (N. Virginia)
    'us-east-2',      # US East (Ohio)
    'us-west-1',      # US West (N. California)
    'us-west-2',      # US West (Oregon)
    'ap-south-1',     # Asia Pacific (Mumbai)
    'ap-southeast-1', # Asia Pacific (Singapore)
    'ap-southeast-2', # Asia Pacific (Sydney)
    'ap-northeast-1', # Asia Pacific (Tokyo)
    'ap-northeast-2', # Asia Pacific (Seoul)
    'ca-central-1',   # Canada (Central)
    'eu-central-1',   # Europe (Frankfurt)
    'eu-west-1',      # Europe (Ireland)
    'eu-west-2',      # Europe (London)
    'eu-west-3',      # Europe (Paris)
    'sa-east-1'       # South America (São Paulo)
]

# ============================================================================
# PROFILE MANAGEMENT CONFIGURATION
# ============================================================================
# Configuration
PLATFORM_DIR = Path.home() / ".platform"
DEPLOYMENTS_DIR = PLATFORM_DIR / "deployments"
TEMPLATES_DIR = PLATFORM_DIR / "templates"
CONFIG_FILE = PLATFORM_DIR / "config.json"

# Ensure directories exist
PLATFORM_DIR.mkdir(exist_ok=True)
DEPLOYMENTS_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = """{
            "default_region": "us-east-1",
            "default_expiration": "7d",
            "aws_account_id": None,
            "default_key_name": "en-field-key",
            "user_profile": {
                "name": None,
                "email": None,
                "org": None,
                "team": None
            },
            "default_tags": {
                "cloud": "aws",
                "environment": "demo"
            },
            "setup_complete": False
        }"""

# ============================================================================
# NOTIFICATION CONFIGURATION
# ============================================================================

# Slack webhook URL for notifications (optional)
#SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL', '')

# Email settings for notifications (optional)
#NOTIFICATION_EMAIL_FROM = os.environ.get('NOTIFICATION_EMAIL_FROM', '')
#NOTIFICATION_EMAIL_TO = os.environ.get('NOTIFICATION_EMAIL_TO', '').split(',') if os.environ.get('NOTIFICATION_EMAIL_TO') else []
#SMTP_SERVER = os.environ.get('SMTP_SERVER', '')
#SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
#SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
#SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')

# ============================================================================
# LOGGING AND MONITORING
# ============================================================================

# Log level for cost management operations
PLATFORM_MANAGEMENT_LOG_LEVEL = os.environ.get('PLATFORM_MANAGEMENT_LOG_LEVEL', 'INFO').upper()

# ============================================================================
# VALIDATION AND SAFETY CHECKS
# ============================================================================

def validate_config():
    """Validate the configuration settings."""
    errors = []
    warnings = []

    # Check required credentials
    if not AWS_PROFILE:
        errors.append("No AWS credentials found. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY.")

    # Check config exists
    if not CONFIG_FILE:
        errors.append(f"Configuration file not found at {CONFIG_FILE}. Initial setup required. Run 'platform setup' first.")

    # Check notification settings
    #if SLACK_WEBHOOK_URL and not SLACK_WEBHOOK_URL.startswith('https://hooks.slack.com/'):
    #    warnings.append("SLACK_WEBHOOK_URL doesn't appear to be a valid Slack webhook URL")

    #if NOTIFICATION_EMAIL_TO and not SMTP_SERVER:
    #    warnings.append("Email notifications configured but no SMTP_SERVER specified")

    # Output any errors or warnings
    if errors:
        print("❌ Configuration errors:")
        for error in errors:
            print(f"  - {error}")
        raise ValueError("Configuration validation failed")

    if warnings:
        print("⚠️  Configuration warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    return True

# Validate configuration when module is imported
if __name__ != "__main__":
    try:
        validate_config()
    except ValueError as e:
        print(f"Configuration validation failed: {e}")
        # Don't raise in non-main context to allow imports to succeed