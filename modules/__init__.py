"""
Platform CLI Modules Package

This package contains all the specialized modules for the Platform CLI tool:
- utils_module: Shared utilities and helpers
- local_cluster_module: Kind cluster management for local development
- connectivity_module: SSH tunnel management for shared data sources
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



from .local_cluster_module import (
    check_kind_available,
    check_docker_available,
    create_kind_cluster,
    destroy_kind_cluster,
    list_local_clusters,
    get_cluster_info
)

from .connectivity_module import (
    enable_data_source,
    disable_data_source,
    get_connection_info,
    list_available_sources,
    is_data_source_connected
)

# Package-level constants
SUPPORTED_REGIONS = [
    'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
    'ap-south-1', 'ap-southeast-1', 'ap-southeast-2',
    'ap-northeast-1', 'ap-northeast-2', 'ca-central-1',
    'eu-central-1', 'eu-west-1', 'eu-west-2', 'eu-west-3',
    'sa-east-1'
]

# Module information for debugging
MODULE_INFO = {
    "utils_module": "Shared utilities and AWS helpers",
    "local_cluster_module": "Kind cluster management for local development",
    "connectivity_module": "SSH tunnel management for shared data sources"
}

def get_module_info():
    """Get information about available modules"""
    return MODULE_INFO


def get_supported_regions():
    """Get list of supported AWS regions"""
    return SUPPORTED_REGIONS

# Validation functions for package health
def validate_all_modules():
    """Validate that all modules can be imported successfully"""
    modules = ['utils_module', 'local_cluster_module', 'connectivity_module']
    results = {}

    for module_name in modules:
        try:
            __import__(f'modules.{module_name}')
            results[module_name] = {'status': 'OK', 'error': None}
        except Exception as e:
            results[module_name] = {'status': 'FAILED', 'error': str(e)}

    return results