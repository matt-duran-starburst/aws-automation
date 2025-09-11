"""
Configuration settings for the Platform CLI tool.
Simplified for shared infrastructure architecture with local development clusters.
"""

import os
import json
from pathlib import Path
from datetime import datetime

# Optional dotenv support
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ============================================================================
# PLATFORM CONFIGURATION
# ============================================================================

# Platform directory structure
PLATFORM_DIR = Path.home() / ".platform"
LOCAL_CLUSTERS_DIR = PLATFORM_DIR / "local_clusters"
CONNECTIVITY_DIR = PLATFORM_DIR / "connectivity"
HELM_DIR = PLATFORM_DIR / "helm"
USAGE_DIR = PLATFORM_DIR / "usage"
CONFIG_FILE = PLATFORM_DIR / "config.json"

# Ensure directories exist
PLATFORM_DIR.mkdir(exist_ok=True)
LOCAL_CLUSTERS_DIR.mkdir(exist_ok=True)
CONNECTIVITY_DIR.mkdir(exist_ok=True)
HELM_DIR.mkdir(exist_ok=True)
USAGE_DIR.mkdir(exist_ok=True)

# Simplified configuration focused on shared infrastructure
DEFAULT_CONFIG = {
    "user_profile": {
        "name": None,
        "email": None,
        "org": None,
        "team": None
    },
    "shared_infrastructure": {
        "admin_access": False,
        "preferred_clouds": ["aws"],
        "cost_center": None,
        "admin_region": "us-east-1"
    },
    "local_clusters": {
        "default_preset": "development",
        "auto_database": True,
        "auto_registry": True,
        "auto_ingress": True
    },
    "connectivity": {
        "ssh_key_path": None,
        "bastion_user": "ubuntu",
        "default_local_ports": {
            "postgres": 5433,
            "mysql": 3307,
            "sqlserver": 1434
        }
    },
    "setup_complete": False
}

# ============================================================================
# PLATFORM CONFIGURATION CLASS
# ============================================================================

class PlatformConfig:
    """Simplified platform configuration management"""

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
                self._deep_merge(config, loaded_config)
                return config
                
            except (json.JSONDecodeError, FileNotFoundError) as e:
                print(f"⚠️ Warning: Could not load config file: {e}")
                print("Using default configuration.")
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()

    def _deep_merge(self, base_dict, update_dict):
        """Deep merge two dictionaries"""
        for key, value in update_dict.items():
            if key in base_dict and isinstance(base_dict[key], dict) and isinstance(value, dict):
                self._deep_merge(base_dict[key], value)
            else:
                base_dict[key] = value

    def save_config(self):
        """Save configuration to file"""
        try:
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

    def get_user_name(self):
        """Get user name from configuration"""
        return self.get("user_profile.name")

    def get_user_team(self):
        """Get user team from configuration"""
        return self.get("user_profile.team")

    def is_admin(self):
        """Check if user has admin access for shared infrastructure"""
        return self.get("shared_infrastructure.admin_access", False)

    def get_preferred_clouds(self):
        """Get list of preferred cloud providers"""
        return self.get("shared_infrastructure.preferred_clouds", ["aws"])

    def get_default_preset(self):
        """Get default cluster preset"""
        return self.get("local_clusters.default_preset", "development")

    def validate(self):
        """Validate configuration and return errors/warnings"""
        errors = []
        warnings = []

        # Check if setup is complete
        if not self.is_setup_complete():
            errors.append("Initial setup not complete. Run 'python3 platform_cli.py setup' first.")

        # Check user profile
        if not self.get_user_email():
            warnings.append("No email configured. Usage tracking will be limited.")

        if not self.get_user_name():
            warnings.append("No name configured. User attribution will be incomplete.")

        # Check admin access for infrastructure operations
        if self.is_admin() and not os.environ.get('AWS_PROFILE'):
            warnings.append("Admin access enabled but no AWS_PROFILE set for infrastructure operations.")

        return errors, warnings

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_config():
    """Get a PlatformConfig instance"""
    return PlatformConfig()

def get_config_value(key, default=None):
    """Quick access to configuration values"""
    config = get_config()
    return config.get(key, default)

def validate_config():
    """Validate the configuration settings"""
    try:
        config = get_config()
        errors, warnings = config.validate()

        if errors:
            print("❌ Configuration errors:")
            for error in errors:
                print(f"  - {error}")

        if warnings:
            print("⚠️  Configuration warnings:")
            for warning in warnings:
                print(f"  - {warning}")

        return len(errors) == 0, errors, warnings
    except Exception as e:
        print(f"❌ Failed to validate configuration: {e}")
        return False, [str(e)], []

# ============================================================================
# CLOUD CREDENTIALS
# ============================================================================

def get_aws_profile():
    """Get AWS profile from environment"""
    return os.environ.get('AWS_PROFILE', '')

def get_gcp_project():
    """Get GCP project from environment"""
    return os.environ.get('GOOGLE_CLOUD_PROJECT', '')

def get_azure_subscription():
    """Get Azure subscription from environment"""
    return os.environ.get('AZURE_SUBSCRIPTION_ID', '')

# ============================================================================
# USAGE TRACKING
# ============================================================================

def log_usage(action, details=None):
    """Log usage for analytics (simplified)"""
    try:
        config = get_config()
        usage_log = {
            "timestamp": str(datetime.now()),
            "user": config.get_user_email() or "unknown",
            "action": action,
            "details": details or {}
        }
        
        # Simple append to daily log file
        log_file = USAGE_DIR / f"usage_{datetime.now().strftime('%Y%m%d')}.jsonl"
        
        with open(log_file, 'a') as f:
            f.write(json.dumps(usage_log) + '\n')
    except Exception:
        # Don't fail operations due to logging issues
        pass

# Initialize when module is imported
if __name__ != "__main__":
    try:
        validate_config()
    except Exception:
        # Don't fail module import due to config issues
        pass