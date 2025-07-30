"""
Platform CLI Modules Package

This package contains all the specialized modules for the Platform CLI tool:
- eks_module: EKS cluster management
- rds_module: RDS database management (PostgreSQL, MySQL, Oracle)
- s3_module: S3 bucket management
- utils_module: Shared utilities and helpers
"""

# Version information
__version__ = "1.0.0"
__author__ = "Platform Team"

# Import key functions for easier access
from .utils_module import (
    validate_aws_credentials,
    check_setup_required,
    get_vpc_subnets,
    parse_expiration,
    generate_deployment_id,
    create_deployment_metadata,
    load_deployment_metadata,
    save_deployment_metadata,
    list_deployments,
    print_deployments_table,
    confirm_action,
    sanitize_name
)

from .eks_module import (
    scale_eks_nodegroups,
    run_eksctl_command,
    generate_eksctl_config,
    get_cluster_vpc_info,
    update_kubeconfig
)

from .rds_module import (
    create_rds_instance,
    get_rds_instance_status,
    delete_rds_instance,
    get_connection_string,
    validate_engine_requirements,
    DATABASE_ENGINES
)

from .s3_module import (
    locate_s3_bucket,
    create_s3_bucket,
    delete_s3_bucket,
    get_bucket_info,
    list_platform_buckets,
    validate_bucket_name
)

# Package-level constants
SUPPORTED_DATABASE_ENGINES = list(DATABASE_ENGINES.keys())
SUPPORTED_REGIONS = [
    'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
    'ap-south-1', 'ap-southeast-1', 'ap-southeast-2',
    'ap-northeast-1', 'ap-northeast-2', 'ca-central-1',
    'eu-central-1', 'eu-west-1', 'eu-west-2', 'eu-west-3',
    'sa-east-1'
]

# Module information for debugging
MODULE_INFO = {
    "eks_module": "EKS cluster lifecycle management",
    "rds_module": "Multi-engine RDS database management",
    "s3_module": "S3 bucket creation and management",
    "utils_module": "Shared utilities and AWS helpers"
}

def get_module_info():
    """Get information about available modules"""
    return MODULE_INFO

def get_supported_engines():
    """Get list of supported database engines"""
    return SUPPORTED_DATABASE_ENGINES

def get_supported_regions():
    """Get list of supported AWS regions"""
    return SUPPORTED_REGIONS

# Validation functions for package health
def validate_all_modules():
    """Validate that all modules can be imported successfully"""
    modules = ['eks_module', 'rds_module', 's3_module', 'utils_module']
    results = {}

    for module_name in modules:
        try:
            __import__(f'modules.{module_name}')
            results[module_name] = {'status': 'OK', 'error': None}
        except Exception as e:
            results[module_name] = {'status': 'FAILED', 'error': str(e)}

    return results