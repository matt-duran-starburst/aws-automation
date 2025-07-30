"""
Configuration settings for the AWS platform management and cost management tools.
Updated for modular architecture.
"""

import os
import json
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

DEFAULT_CONFIG = {
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
}

# ============================================================================
# NOTIFICATION CONFIGURATION
# ============================================================================

# Slack webhook URL for notifications (optional)
# SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL', '')

# Email settings for notifications (optional)
# NOTIFICATION_EMAIL_FROM = os.environ.get('NOTIFICATION_EMAIL_FROM', '')
# NOTIFICATION_EMAIL_TO = os.environ.get('NOTIFICATION_EMAIL_TO', '').split(',') if os.environ.get('NOTIFICATION_EMAIL_TO') else []
# SMTP_SERVER = os.environ.get('SMTP_SERVER', '')
# SMTP_PORT = int(os.environ.get('SMTP_PORT', '587')) if os.environ.get('SMTP_PORT') else 587
# SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
# SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')

# ============================================================================
# LOGGING AND MONITORING
# ============================================================================

# Log level for cost management operations
PLATFORM_MANAGEMENT_LOG_LEVEL = os.environ.get('PLATFORM_MANAGEMENT_LOG_LEVEL', 'INFO').upper()

# ============================================================================
# PLATFORM CONFIGURATION CLASS
# ============================================================================

class PlatformConfig:
    """Handle platform configuration with improved error handling and validation"""

    def __init__(self):
        self.config_path = CONFIG_FILE
        self.config = self.load_config()

    def load_config(self):
        """Load configuration from file or create default"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    loaded_config = json.load(f)

                # Merge with default config to ensure all keys exist
                config = DEFAULT_CONFIG.copy()
                config.update(loaded_config)

                # Ensure nested dictionaries are properly merged
                if "user_profile" in loaded_config:
                    config["user_profile"].update(loaded_config["user_profile"])
                if "default_tags" in loaded_config:
                    config["default_tags"].update(loaded_config["default_tags"])

                return config
            except (json.JSONDecodeError, FileNotFoundError) as e:
                print(f"⚠️ Warning: Could not load config file: {e}")
                print("Using default configuration.")
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        """Save configuration to file with error handling"""
        try:
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"❌ Error saving configuration: {e}")
            raise

    def get(self, key, default=None):
        """Get configuration value with dot notation support"""
        keys = key.split('.')
        value = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key, value):
        """Set configuration value with dot notation support"""
        keys = key.split('.')
        config_ref = self.config

        # Navigate to the parent of the target key
        for k in keys[:-1]:
            if k not in config_ref:
                config_ref[k] = {}
            config_ref = config_ref[k]

        # Set the value
        config_ref[keys[-1]] = value

    def is_setup_complete(self):
        """Check if initial setup is complete"""
        return self.config.get("setup_complete", False)

    def get_user_email(self):
        """Get user email from configuration"""
        return self.get("user_profile.email")

    def get_default_region(self):
        """Get default AWS region"""
        return self.get("default_region", "us-east-1")

    def get_default_tags(self):
        """Get default tags for resources"""
        return self.config.get("default_tags", {}).copy()

    def validate(self):
        """Validate configuration and return errors/warnings"""
        errors = []
        warnings = []

        # Check if setup is complete
        if not self.is_setup_complete():
            errors.append("Initial setup not complete. Run 'platform setup' first.")

        # Check user profile
        user_profile = self.config.get("user_profile", {})
        if not user_profile.get("email"):
            warnings.append("No email configured. Some features may require manual owner specification.")

        if not user_profile.get("name"):
            warnings.append("No name configured. Resource tags may be incomplete.")

        # Check AWS configuration
        if not self.config.get("aws_account_id"):
            warnings.append("AWS account ID not detected. Run commands to refresh AWS info.")

        # Check required settings
        if not self.get_default_region():
            errors.append("No default region configured.")

        if not self.config.get("default_key_name"):
            warnings.append("No default SSH key configured. EKS deployments may require manual key specification.")

        return errors, warnings

# ============================================================================
# VALIDATION AND SAFETY CHECKS
# ============================================================================

def validate_config():
    """Validate the configuration settings."""
    errors = []
    warnings = []

    # Check required credentials
    if not AWS_PROFILE:
        warnings.append("No AWS_PROFILE set. Using default credentials or IAM role.")

    # Check config exists
    if not CONFIG_FILE.exists():
        errors.append(f"Configuration file not found at {CONFIG_FILE}. Run 'platform setup' first.")

    # # Check notification settings
    # if SLACK_WEBHOOK_URL and not SLACK_WEBHOOK_URL.startswith('https://hooks.slack.com/'):
    #     warnings.append("SLACK_WEBHOOK_URL doesn't appear to be a valid Slack webhook URL")

    # if NOTIFICATION_EMAIL_TO and not SMTP_SERVER:
    #     warnings.append("Email notifications configured but no SMTP_SERVER specified")

    # Output any errors or warnings
    if errors:
        print("❌ Configuration errors:")
        for error in errors:
            print(f"  - {error}")

    if warnings:
        print("⚠️  Configuration warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    return len(errors) == 0, errors, warnings

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_config():
    """Get a PlatformConfig instance (singleton-like behavior)"""
    return PlatformConfig()

def ensure_directories():
    """Ensure all required directories exist"""
    directories = [PLATFORM_DIR, DEPLOYMENTS_DIR, TEMPLATES_DIR]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

def get_deployment_dir(deployment_id):
    """Get deployment directory path"""
    return DEPLOYMENTS_DIR / deployment_id

def get_config_value(key, default=None):
    """Quick access to configuration values"""
    config = get_config()
    return config.get(key, default)

# Initialize directories when module is imported
ensure_directories()

# Validate configuration when module is imported (but don't fail)
if __name__ != "__main__":
    try:
        is_valid, errors, warnings = validate_config()
        if not is_valid and errors:
            # Only print errors that would prevent operation
            critical_errors = [e for e in errors if "setup" not in e.lower()]
            if critical_errors:
                print("❌ Critical configuration errors:")
                for error in critical_errors:
                    print(f"  - {error}")
    except Exception as e:
        # Don't fail module import due to config validation issues
        pass