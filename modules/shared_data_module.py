"""
Shared data sources management module for discovering and managing connections
to Pulumi-provisioned databases across AWS, GCP, and Azure.
"""

import click
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Import from parent directory and other modules
import sys
sys.path.append(str(Path(__file__).parent.parent))
from config import PlatformConfig, PLATFORM_DIR

# Try to import from other modules with fallback
try:
    from modules.pulumi_module import get_stack_outputs, get_database_endpoints, get_infrastructure_status
except ImportError:
    # Fallback functions if pulumi_module is not available
    def get_stack_outputs(stack_name: str) -> Dict[str, Any]:
        return {}
    
    def get_database_endpoints() -> Dict[str, Any]:
        return {}
    
    def get_infrastructure_status() -> Dict[str, Any]:
        return {"error": "Pulumi module not available"}

# Data source profiles directory
PROFILES_DIR = PLATFORM_DIR / "connectivity" / "connection_profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)

# Available data source types and their default configurations
DATA_SOURCE_TYPES = {
    "aws-postgres": {
        "name": "AWS PostgreSQL (RDS)",
        "type": "postgresql",
        "cloud": "aws",
        "default_port": 5432,
        "sample_datasets": ["tpch", "tpcds", "northwind", "sakila"],
        "description": "Shared PostgreSQL database with sample datasets for development and testing"
    },
    "aws-mysql": {
        "name": "AWS MySQL (RDS)",
        "type": "mysql", 
        "cloud": "aws",
        "default_port": 3306,
        "sample_datasets": ["tpch", "tpcds", "employees", "world"],
        "description": "Shared MySQL database with sample datasets for compatibility testing"
    },
    "gcp-postgres": {
        "name": "GCP PostgreSQL (Cloud SQL)",
        "type": "postgresql",
        "cloud": "gcp",
        "default_port": 5432,
        "sample_datasets": ["tpch", "tpcds", "northwind"],
        "description": "Shared PostgreSQL on GCP with multi-region sample data"
    },
    "gcp-bigquery": {
        "name": "GCP BigQuery",
        "type": "bigquery",
        "cloud": "gcp",
        "default_port": 443,
        "sample_datasets": ["tpch", "tpcds", "public_datasets", "covid19", "census"],
        "description": "BigQuery data warehouse with public datasets and sample data"
    },
    "azure-sqlserver": {
        "name": "Azure SQL Server",
        "type": "sqlserver",
        "cloud": "azure", 
        "default_port": 1433,
        "sample_datasets": ["tpch", "tpcds", "adventureworks"],
        "description": "Azure SQL Server with enterprise sample databases"
    },
    "azure-synapse": {
        "name": "Azure Synapse Analytics",
        "type": "synapse",
        "cloud": "azure",
        "default_port": 1433,
        "sample_datasets": ["tpch", "tpcds", "retail_analytics", "iot_data"],
        "description": "Azure Synapse data warehouse for analytics workloads"
    }
}

def get_available_clouds() -> Dict[str, bool]:
    """Check which cloud credentials are available"""
    try:
        infra_status = get_infrastructure_status()
        return infra_status.get("credentials", {})
    except Exception:
        # Fallback credential check
        clouds = {}
        
        # Check AWS
        try:
            result = subprocess.run(
                ["aws", "sts", "get-caller-identity"],
                capture_output=True,
                text=True,
                timeout=10
            )
            clouds["aws"] = result.returncode == 0
        except Exception:
            clouds["aws"] = False
        
        # Check GCP
        try:
            result = subprocess.run(
                ["gcloud", "auth", "list", "--filter=status:ACTIVE"],
                capture_output=True,
                text=True,
                timeout=10
            )
            clouds["gcp"] = result.returncode == 0 and "ACTIVE" in result.stdout
        except Exception:
            clouds["gcp"] = False
        
        # Check Azure
        try:
            result = subprocess.run(
                ["az", "account", "show"],
                capture_output=True,
                text=True,
                timeout=10
            )
            clouds["azure"] = result.returncode == 0
        except Exception:
            clouds["azure"] = False
        
        return clouds

def list_available_sources() -> Dict[str, Any]:
    """List all available shared data sources"""
    available_clouds = get_available_clouds()
    
    # Get actual infrastructure status
    try:
        infra_status = get_infrastructure_status()
        deployed_stacks = infra_status.get("stacks", {})
    except Exception:
        deployed_stacks = {}
    
    # Get database endpoints from infrastructure
    try:
        db_endpoints = get_database_endpoints()
    except Exception:
        db_endpoints = {}
    
    sources = {}
    
    for source_id, source_config in DATA_SOURCE_TYPES.items():
        cloud = source_config["cloud"]
        
        # Check if this cloud has credentials
        has_credentials = available_clouds.get(cloud, False)
        
        # Check if infrastructure is deployed
        is_deployed = bool(deployed_stacks.get("shared-databases", {}).get("exists", False))
        
        # Check if endpoint is available
        endpoint_info = db_endpoints.get(f"{cloud}_{source_config['type']}", {})
        has_endpoint = bool(endpoint_info.get("endpoint"))
        
        # Determine availability status
        if not has_credentials:
            status = "no_credentials"
            status_message = f"No {cloud.upper()} credentials configured"
        elif not is_deployed:
            status = "not_deployed" 
            status_message = "Shared infrastructure not deployed"
        elif not has_endpoint:
            status = "no_endpoint"
            status_message = "Database endpoint not available"
        else:
            status = "available"
            status_message = "Ready to connect"
        
        sources[source_id] = {
            "name": source_config["name"],
            "type": source_config["type"],
            "cloud": cloud,
            "description": source_config["description"],
            "default_port": source_config["default_port"],
            "sample_datasets": source_config["sample_datasets"],
            "status": status,
            "status_message": status_message,
            "has_credentials": has_credentials,
            "is_deployed": is_deployed,
            "endpoint_info": endpoint_info
        }
    
    # Get connection statistics
    stats = _get_connection_stats()
    
    return {
        "success": True,
        "sources": sources,
        "available_count": len([s for s in sources.values() if s["status"] == "available"]),
        "total_count": len(sources),
        "available_clouds": [cloud for cloud, valid in available_clouds.items() if valid],
        "infrastructure_deployed": is_deployed,
        "connection_stats": stats
    }

def get_source_status(source_id: str) -> Dict[str, Any]:
    """Get detailed status of a specific data source"""
    if source_id not in DATA_SOURCE_TYPES:
        return {
            "success": False,
            "error": f"Unknown data source: {source_id}. Available: {list(DATA_SOURCE_TYPES.keys())}"
        }
    
    source_config = DATA_SOURCE_TYPES[source_id]
    cloud = source_config["cloud"]
    
    # Get basic availability info
    available_sources = list_available_sources()
    if not available_sources["success"]:
        return available_sources
    
    source_info = available_sources["sources"][source_id]
    
    # Get detailed connectivity information
    connectivity_details = _check_connectivity_details(source_id, source_config)
    
    # Get usage statistics
    usage_stats = _get_source_usage_stats(source_id)
    
    return {
        "success": True,
        "source_id": source_id,
        "basic_info": source_info,
        "connectivity": connectivity_details,
        "usage_stats": usage_stats,
        "last_checked": datetime.now().isoformat()
    }

def _check_connectivity_details(source_id: str, source_config: Dict[str, Any]) -> Dict[str, Any]:
    """Check detailed connectivity information for a data source"""
    cloud = source_config["cloud"]
    
    # Get database endpoints
    try:
        db_endpoints = get_database_endpoints()
        endpoint_info = db_endpoints.get(f"{cloud}_{source_config['type']}", {})
    except Exception:
        endpoint_info = {}
    
    # Get bastion host information
    try:
        connectivity_outputs = get_stack_outputs("connectivity")
        bastions = connectivity_outputs.get("bastions", {})
        bastion_info = bastions.get(cloud, {})
    except Exception:
        bastion_info = {}
    
    # Check if SSH tunnel would be required
    requires_tunnel = bool(endpoint_info.get("endpoint") and bastion_info.get("public_ip"))
    
    connectivity = {
        "endpoint": endpoint_info.get("endpoint"),
        "port": endpoint_info.get("port", source_config["default_port"]),
        "database": endpoint_info.get("database"),
        "requires_ssh_tunnel": requires_tunnel,
        "bastion_host": bastion_info.get("public_ip"),
        "bastion_user": bastion_info.get("user", "ubuntu"),
        "connection_type": "tunnel" if requires_tunnel else "direct"
    }
    
    # Generate local port for tunneling
    if requires_tunnel:
        connectivity["local_port"] = _get_next_available_port(source_config["default_port"])
    
    # Check if connection profile exists
    profile_file = PROFILES_DIR / f"{source_id}.json"
    connectivity["profile_exists"] = profile_file.exists()
    connectivity["profile_path"] = str(profile_file)
    
    return connectivity

def _get_source_usage_stats(source_id: str) -> Dict[str, Any]:
    """Get usage statistics for a data source"""
    # This would integrate with actual usage tracking
    # For now, return placeholder data
    stats = {
        "total_connections": 0,
        "active_connections": 0,
        "last_connected": None,
        "most_used_datasets": [],
        "connection_duration_avg": 0
    }
    
    # Try to read from usage tracking file if it exists
    usage_file = PLATFORM_DIR / "usage" / f"{source_id}_stats.json"
    if usage_file.exists():
        try:
            with open(usage_file, 'r') as f:
                stored_stats = json.load(f)
                stats.update(stored_stats)
        except Exception:
            pass  # Use default stats
    
    return stats

def _get_connection_stats() -> Dict[str, Any]:
    """Get overall connection statistics"""
    stats = {
        "total_connections_today": 0,
        "active_connections": 0,
        "most_popular_sources": [],
        "peak_usage_time": "N/A"
    }
    
    # Try to read from overall stats file
    stats_file = PLATFORM_DIR / "usage" / "daily_stats.json"
    if stats_file.exists():
        try:
            with open(stats_file, 'r') as f:
                stored_stats = json.load(f)
                if stored_stats.get("date") == datetime.now().strftime("%Y-%m-%d"):
                    stats.update(stored_stats.get("stats", {}))
        except Exception:
            pass
    
    return stats

def _get_next_available_port(base_port: int) -> int:
    """Find the next available local port starting from base_port"""
    import socket
    
    for port in range(base_port, base_port + 100):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return port
        except OSError:
            continue
    
    # Fallback to a high port if all base ports are taken
    return base_port + 1000

def create_connection_profile(source_id: str, custom_settings: Dict[str, Any] = None) -> Dict[str, Any]:
    """Create a connection profile for a data source"""
    if source_id not in DATA_SOURCE_TYPES:
        return {
            "success": False,
            "error": f"Unknown data source: {source_id}"
        }
    
    # Get source status first
    status_result = get_source_status(source_id)
    if not status_result["success"]:
        return status_result
    
    source_info = status_result["basic_info"]
    connectivity = status_result["connectivity"]
    
    if source_info["status"] != "available":
        return {
            "success": False,
            "error": f"Data source not available: {source_info['status_message']}"
        }
    
    # Create connection profile
    profile = {
        "source_id": source_id,
        "name": source_info["name"],
        "type": source_info["type"],
        "cloud": source_info["cloud"],
        "description": source_info["description"],
        "created": datetime.now().isoformat(),
        "connection": {
            "host": "localhost" if connectivity["requires_ssh_tunnel"] else connectivity["endpoint"],
            "port": connectivity.get("local_port", connectivity["port"]),
            "database": connectivity.get("database", "shared_db"),
            "username": "starburst",  # Default shared username
            "password_env": f"STARBURST_{source_id.upper().replace('-', '_')}_PASSWORD"
        },
        "ssh_tunnel": {
            "enabled": connectivity["requires_ssh_tunnel"],
            "bastion_host": connectivity.get("bastion_host"),
            "bastion_user": connectivity.get("bastion_user", "ubuntu"),
            "target_host": connectivity["endpoint"],
            "target_port": connectivity["port"],
            "local_port": connectivity.get("local_port")
        } if connectivity["requires_ssh_tunnel"] else None,
        "sample_datasets": source_info["sample_datasets"],
        "starburst_catalog": {
            "name": f"{source_info['cloud']}_{source_info['type']}_shared",
            "connector": source_info["type"],
            "properties": _generate_catalog_properties(source_info, connectivity)
        }
    }
    
    # Apply custom settings if provided
    if custom_settings:
        profile = _merge_profile_settings(profile, custom_settings)
    
    # Save profile
    profile_file = PROFILES_DIR / f"{source_id}.json"
    try:
        with open(profile_file, 'w') as f:
            json.dump(profile, f, indent=2)
        
        return {
            "success": True,
            "source_id": source_id,
            "profile_file": str(profile_file),
            "profile": profile
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to save connection profile: {str(e)}"
        }

def _generate_catalog_properties(source_info: Dict[str, Any], connectivity: Dict[str, Any]) -> Dict[str, str]:
    """Generate Starburst catalog properties for a data source"""
    props = {}
    
    if source_info["type"] == "postgresql":
        props = {
            "connection-url": f"jdbc:postgresql://{connectivity.get('local_port', connectivity['port'])}/{connectivity.get('database', 'shared_db')}",
            "connection-user": "starburst",
            "connection-password": "${ENV:STARBURST_" + source_info["cloud"].upper() + "_POSTGRES_PASSWORD}"
        }
    elif source_info["type"] == "mysql":
        props = {
            "connection-url": f"jdbc:mysql://localhost:{connectivity.get('local_port', connectivity['port'])}/{connectivity.get('database', 'shared_db')}",
            "connection-user": "starburst", 
            "connection-password": "${ENV:STARBURST_" + source_info["cloud"].upper() + "_MYSQL_PASSWORD}"
        }
    elif source_info["type"] == "bigquery":
        props = {
            "project-id": "starburst-shared-dev",
            "parent-project-id": "starburst-shared-dev"
        }
    elif source_info["type"] in ["sqlserver", "synapse"]:
        props = {
            "connection-url": f"jdbc:sqlserver://localhost:{connectivity.get('local_port', connectivity['port'])};database={connectivity.get('database', 'shared_db')}",
            "connection-user": "starburst",
            "connection-password": "${ENV:STARBURST_" + source_info["cloud"].upper() + "_SQLSERVER_PASSWORD}"
        }
    
    return props

def _merge_profile_settings(profile: Dict[str, Any], custom_settings: Dict[str, Any]) -> Dict[str, Any]:
    """Merge custom settings into connection profile"""
    # Deep merge custom settings
    import copy
    merged = copy.deepcopy(profile)
    
    for key, value in custom_settings.items():
        if isinstance(value, dict) and key in merged:
            merged[key].update(value)
        else:
            merged[key] = value
    
    return merged

def list_connection_profiles() -> Dict[str, Any]:
    """List all saved connection profiles"""
    profiles = {}
    
    for profile_file in PROFILES_DIR.glob("*.json"):
        source_id = profile_file.stem
        
        try:
            with open(profile_file, 'r') as f:
                profile_data = json.load(f)
                
                profiles[source_id] = {
                    "source_id": source_id,
                    "name": profile_data.get("name"),
                    "type": profile_data.get("type"), 
                    "cloud": profile_data.get("cloud"),
                    "created": profile_data.get("created"),
                    "tunnel_required": profile_data.get("ssh_tunnel", {}).get("enabled", False),
                    "profile_file": str(profile_file)
                }
        except Exception as e:
            profiles[source_id] = {
                "source_id": source_id,
                "error": f"Failed to load profile: {str(e)}",
                "profile_file": str(profile_file)
            }
    
    return {
        "success": True,
        "profiles": profiles,
        "count": len(profiles)
    }

def delete_connection_profile(source_id: str) -> Dict[str, Any]:
    """Delete a connection profile"""
    profile_file = PROFILES_DIR / f"{source_id}.json"
    
    if not profile_file.exists():
        return {
            "success": False,
            "error": f"No connection profile found for {source_id}"
        }
    
    try:
        profile_file.unlink()
        return {
            "success": True,
            "source_id": source_id,
            "message": "Connection profile deleted successfully"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to delete profile: {str(e)}"
        }

def validate_source_connectivity(source_id: str) -> Dict[str, Any]:
    """Test connectivity to a data source"""
    if source_id not in DATA_SOURCE_TYPES:
        return {
            "success": False,
            "error": f"Unknown data source: {source_id}"
        }
    
    # Get source status
    status_result = get_source_status(source_id)
    if not status_result["success"]:
        return status_result
    
    source_info = status_result["basic_info"]
    connectivity = status_result["connectivity"]
    
    validation_results = {
        "source_id": source_id,
        "checks": {},
        "overall_status": "unknown"
    }
    
    # Check 1: Infrastructure deployed
    validation_results["checks"]["infrastructure"] = {
        "status": "pass" if source_info["is_deployed"] else "fail",
        "message": "Infrastructure deployed" if source_info["is_deployed"] else "Infrastructure not deployed"
    }
    
    # Check 2: Credentials available
    validation_results["checks"]["credentials"] = {
        "status": "pass" if source_info["has_credentials"] else "fail", 
        "message": "Cloud credentials configured" if source_info["has_credentials"] else "Cloud credentials missing"
    }
    
    # Check 3: Endpoint available
    validation_results["checks"]["endpoint"] = {
        "status": "pass" if connectivity["endpoint"] else "fail",
        "message": f"Endpoint available: {connectivity['endpoint']}" if connectivity["endpoint"] else "No endpoint available"
    }
    
    # Check 4: Bastion host (if required)
    if connectivity["requires_ssh_tunnel"]:
        validation_results["checks"]["bastion"] = {
            "status": "pass" if connectivity["bastion_host"] else "fail",
            "message": f"Bastion host available: {connectivity['bastion_host']}" if connectivity["bastion_host"] else "Bastion host not available"
        }
    
    # Check 5: Connection profile exists
    validation_results["checks"]["profile"] = {
        "status": "pass" if connectivity["profile_exists"] else "warning",
        "message": "Connection profile exists" if connectivity["profile_exists"] else "No connection profile (run 'connect enable' to create)"
    }
    
    # Determine overall status
    failed_checks = [check for check in validation_results["checks"].values() if check["status"] == "fail"]
    if failed_checks:
        validation_results["overall_status"] = "fail"
    elif any(check["status"] == "warning" for check in validation_results["checks"].values()):
        validation_results["overall_status"] = "warning"
    else:
        validation_results["overall_status"] = "pass"
    
    return {
        "success": True,
        "validation": validation_results
    }

def get_sample_datasets_info(source_id: str) -> Dict[str, Any]:
    """Get information about available sample datasets"""
    if source_id not in DATA_SOURCE_TYPES:
        return {
            "success": False,
            "error": f"Unknown data source: {source_id}"
        }
    
    source_config = DATA_SOURCE_TYPES[source_id]
    datasets = []
    
    # Define dataset information
    dataset_info = {
        "tpch": {
            "name": "TPC-H Decision Support Benchmark",
            "description": "Industry standard benchmark for decision support systems",
            "tables": ["customer", "lineitem", "nation", "orders", "part", "partsupp", "region", "supplier"],
            "size": "1GB",
            "use_case": "Performance testing, query optimization"
        },
        "tpcds": {
            "name": "TPC-DS Decision Support Benchmark", 
            "description": "Advanced benchmark for business intelligence workloads",
            "tables": ["catalog_sales", "store_sales", "web_sales", "customer", "item", "store", "warehouse"],
            "size": "10GB",
            "use_case": "Complex analytics, BI dashboard testing"
        },
        "northwind": {
            "name": "Northwind Traders Sample Database",
            "description": "Classic sample database with business data",
            "tables": ["customers", "employees", "orders", "products", "suppliers", "categories"],
            "size": "5MB",
            "use_case": "Application development, learning SQL"
        },
        "sakila": {
            "name": "Sakila DVD Rental Database",
            "description": "Sample database for DVD rental business",
            "tables": ["actor", "film", "customer", "rental", "payment", "inventory"],
            "size": "3MB", 
            "use_case": "Learning joins, complex queries"
        },
        "employees": {
            "name": "Employee Sample Database",
            "description": "Large employee database with historical data",
            "tables": ["employees", "salaries", "titles", "departments", "dept_emp", "dept_manager"],
            "size": "160MB",
            "use_case": "Time series analysis, HR analytics"
        },
        "world": {
            "name": "World Database",
            "description": "Geographic and demographic world data",
            "tables": ["country", "city", "countrylanguage"],
            "size": "1MB",
            "use_case": "Geographic queries, demographic analysis"
        },
        "adventureworks": {
            "name": "AdventureWorks Sample Database",
            "description": "Microsoft's comprehensive business sample database",
            "tables": ["person", "product", "sales", "purchasing", "humanresources"],
            "size": "180MB",
            "use_case": "Enterprise scenarios, complex business logic"
        },
        "public_datasets": {
            "name": "BigQuery Public Datasets",
            "description": "Google's collection of public datasets",
            "tables": ["Various public tables"],
            "size": "Multi-TB",
            "use_case": "Real-world data analysis, research"
        },
        "covid19": {
            "name": "COVID-19 Data",
            "description": "Comprehensive COVID-19 datasets",
            "tables": ["cases", "deaths", "vaccinations", "mobility"],
            "size": "100MB",
            "use_case": "Time series analysis, public health research"
        },
        "census": {
            "name": "US Census Data",
            "description": "US Census Bureau demographic data",
            "tables": ["population", "demographics", "economic_data"],
            "size": "500MB",
            "use_case": "Demographic analysis, market research"
        },
        "retail_analytics": {
            "name": "Retail Analytics Dataset",
            "description": "Synthetic retail transaction data",
            "tables": ["transactions", "customers", "products", "stores"],
            "size": "2GB",
            "use_case": "Retail analytics, customer segmentation"
        },
        "iot_data": {
            "name": "IoT Sensor Data",
            "description": "Time series IoT sensor measurements",
            "tables": ["sensor_readings", "devices", "locations"],
            "size": "5GB",
            "use_case": "IoT analytics, time series forecasting"
        }
    }
    
    # Get datasets available for this source
    for dataset_name in source_config["sample_datasets"]:
        if dataset_name in dataset_info:
            datasets.append({
                "name": dataset_name,
                **dataset_info[dataset_name]
            })
    
    return {
        "success": True,
        "source_id": source_id,
        "source_name": source_config["name"],
        "datasets": datasets,
        "total_datasets": len(datasets)
    }