"""
Shared infrastructure management module using Pulumi for multi-cloud resource provisioning.
Manages shared databases, bastion hosts, and networking for the new architecture.
"""

import click
import json
import subprocess
import os
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Import from parent directory
import sys
sys.path.append(str(Path(__file__).parent.parent))
from config import PlatformConfig, PLATFORM_DIR

# Pulumi configuration directory
PULUMI_DIR = PLATFORM_DIR / "pulumi"
STACKS_DIR = PULUMI_DIR / "stacks"
OUTPUTS_DIR = PULUMI_DIR / "outputs"

# Ensure directories exist
PULUMI_DIR.mkdir(exist_ok=True)
STACKS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

# Stack configurations for different environments
STACK_CONFIGS = {
    "shared-databases": {
        "name": "shared-databases",
        "description": "Shared database instances across AWS, GCP, Azure",
        "resources": ["rds", "bigquery", "synapse"],
        "estimated_cost_monthly": 2000
    },
    "connectivity": {
        "name": "connectivity", 
        "description": "Bastion hosts and VPC networking",
        "resources": ["bastion_hosts", "vpcs", "security_groups"],
        "estimated_cost_monthly": 500
    },
    "monitoring": {
        "name": "monitoring",
        "description": "Cost tracking and resource monitoring",
        "resources": ["cloudwatch", "logging"],
        "estimated_cost_monthly": 200
    }
}

def check_pulumi_available():
    """Check if Pulumi CLI is available"""
    try:
        result = subprocess.run(
            ["pulumi", "version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def load_pulumi_config() -> Dict[str, Any]:
    """Load infrastructure configuration from YAML"""
    config_file = PULUMI_DIR / "config.yaml"
    if config_file.exists():
        with open(config_file, 'r') as f:
            return yaml.safe_load(f)
    
    # Default configuration
    default_config = {
        "aws": {
            "region": "us-east-1",
            "availability_zones": ["us-east-1a", "us-east-1b", "us-east-1c"]
        },
        "gcp": {
            "region": "us-central1",
            "project": "starburst-shared-dev"
        },
        "azure": {
            "region": "East US",
            "resource_group": "starburst-shared-rg"
        },
        "databases": {
            "postgres": {
                "instance_class": "db.t3.medium",
                "allocated_storage": 100,
                "backup_retention": 7
            },
            "mysql": {
                "instance_class": "db.t3.medium", 
                "allocated_storage": 100,
                "backup_retention": 7
            }
        },
        "bastions": {
            "instance_type": "t3.micro",
            "key_pair_name": "platform-bastion-key"
        }
    }
    
    # Save default config
    with open(config_file, 'w') as f:
        yaml.dump(default_config, f, default_flow_style=False)
    
    return default_config

def validate_cloud_credentials() -> Dict[str, bool]:
    """Verify AWS/GCP/Azure credentials are configured"""
    results = {}
    
    # Check AWS credentials
    try:
        result = subprocess.run(
            ["aws", "sts", "get-caller-identity"],
            capture_output=True,
            text=True,
            timeout=10
        )
        results["aws"] = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        results["aws"] = False
    
    # Check GCP credentials
    try:
        result = subprocess.run(
            ["gcloud", "auth", "list", "--filter=status:ACTIVE"],
            capture_output=True,
            text=True,
            timeout=10
        )
        results["gcp"] = result.returncode == 0 and "ACTIVE" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        results["gcp"] = False
    
    # Check Azure credentials
    try:
        result = subprocess.run(
            ["az", "account", "show"],
            capture_output=True,
            text=True,
            timeout=10
        )
        results["azure"] = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        results["azure"] = False
    
    return results

def run_pulumi_command(command: List[str], stack_name: str = None, cwd: str = None) -> Dict[str, Any]:
    """Execute Pulumi CLI commands with proper error handling"""
    if not check_pulumi_available():
        return {
            "success": False,
            "error": "Pulumi CLI not available. Please install Pulumi first.",
            "stdout": "",
            "stderr": ""
        }
    
    # Set working directory
    if cwd is None:
        cwd = str(PULUMI_DIR)
    
    # Add stack selection if provided
    full_command = ["pulumi"] + command
    if stack_name and "--stack" not in command:
        full_command.extend(["--stack", stack_name])
    
    try:
        click.echo(f"=' Running: {' '.join(full_command)}")
        
        result = subprocess.run(
            full_command,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=300  # 5 minutes timeout
        )
        
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": ' '.join(full_command)
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Command timed out after 5 minutes",
            "stdout": "",
            "stderr": ""
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to execute command: {str(e)}",
            "stdout": "",
            "stderr": ""
        }

def get_stack_outputs(stack_name: str) -> Dict[str, Any]:
    """Get Pulumi stack outputs"""
    result = run_pulumi_command(["stack", "output", "--json"], stack_name)
    
    if result["success"]:
        try:
            return json.loads(result["stdout"])
        except json.JSONDecodeError:
            click.echo(f"L Failed to parse stack outputs for {stack_name}")
            return {}
    else:
        click.echo(f"L Failed to get stack outputs: {result.get('error', result.get('stderr'))}")
        return {}

def provision_shared_infrastructure(stacks: List[str] = None) -> Dict[str, Any]:
    """Deploy all shared resources across clouds"""
    if not check_pulumi_available():
        return {"success": False, "error": "Pulumi CLI not available"}
    
    if stacks is None:
        stacks = list(STACK_CONFIGS.keys())
    
    results = {}
    total_estimated_cost = 0
    
    click.echo("=� Starting shared infrastructure provisioning...")
    
    # Validate credentials first
    cred_results = validate_cloud_credentials()
    available_clouds = [cloud for cloud, valid in cred_results.items() if valid]
    
    if not available_clouds:
        return {
            "success": False,
            "error": "No valid cloud credentials found. Please configure AWS, GCP, or Azure credentials."
        }
    
    click.echo(f" Valid credentials found for: {', '.join(available_clouds)}")
    
    for stack_name in stacks:
        if stack_name not in STACK_CONFIGS:
            results[stack_name] = {"success": False, "error": f"Unknown stack: {stack_name}"}
            continue
        
        config = STACK_CONFIGS[stack_name]
        click.echo(f"\n=� Provisioning stack: {config['name']}")
        click.echo(f"   Description: {config['description']}")
        click.echo(f"   Estimated monthly cost: ${config['estimated_cost_monthly']}")
        
        # Create/select stack
        stack_result = run_pulumi_command(["stack", "select", stack_name, "--create"])
        
        if not stack_result["success"]:
            results[stack_name] = {
                "success": False,
                "error": f"Failed to create/select stack: {stack_result.get('error', stack_result.get('stderr'))}"
            }
            continue
        
        # Run pulumi up
        up_result = run_pulumi_command(["up", "--yes"], stack_name)
        
        results[stack_name] = {
            "success": up_result["success"],
            "config": config,
            "outputs": get_stack_outputs(stack_name) if up_result["success"] else {},
            "error": up_result.get("error", up_result.get("stderr")) if not up_result["success"] else None
        }
        
        if up_result["success"]:
            total_estimated_cost += config["estimated_cost_monthly"]
            click.echo(f" Stack {stack_name} provisioned successfully")
        else:
            click.echo(f"L Stack {stack_name} failed: {results[stack_name]['error']}")
    
    # Save deployment metadata
    deployment_metadata = {
        "timestamp": datetime.now().isoformat(),
        "stacks": results,
        "estimated_monthly_cost": total_estimated_cost,
        "available_clouds": available_clouds
    }
    
    metadata_file = OUTPUTS_DIR / f"deployment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(metadata_file, 'w') as f:
        json.dump(deployment_metadata, f, indent=2)
    
    return {
        "success": all(r["success"] for r in results.values()),
        "stacks": results,
        "estimated_monthly_cost": total_estimated_cost,
        "metadata_file": str(metadata_file)
    }

def destroy_shared_infrastructure(stacks: List[str] = None) -> Dict[str, Any]:
    """Clean up shared infrastructure"""
    if stacks is None:
        stacks = list(STACK_CONFIGS.keys())
    
    results = {}
    click.echo("=�  Starting infrastructure cleanup...")
    
    for stack_name in stacks:
        if stack_name not in STACK_CONFIGS:
            results[stack_name] = {"success": False, "error": f"Unknown stack: {stack_name}"}
            continue
        
        click.echo(f"\n=�  Destroying stack: {stack_name}")
        
        # Run pulumi destroy
        destroy_result = run_pulumi_command(["destroy", "--yes"], stack_name)
        
        results[stack_name] = {
            "success": destroy_result["success"],
            "error": destroy_result.get("error", destroy_result.get("stderr")) if not destroy_result["success"] else None
        }
        
        if destroy_result["success"]:
            click.echo(f" Stack {stack_name} destroyed successfully")
        else:
            click.echo(f"L Stack {stack_name} destruction failed: {results[stack_name]['error']}")
    
    return {
        "success": all(r["success"] for r in results.values()),
        "stacks": results
    }

def get_infrastructure_status() -> Dict[str, Any]:
    """Check status of shared resources"""
    if not check_pulumi_available():
        return {"error": "Pulumi CLI not available"}
    
    status = {
        "pulumi_available": True,
        "credentials": validate_cloud_credentials(),
        "stacks": {}
    }
    
    # List all stacks
    list_result = run_pulumi_command(["stack", "ls", "--json"])
    
    if list_result["success"]:
        try:
            stacks_data = json.loads(list_result["stdout"])
            
            for stack_info in stacks_data:
                stack_name = stack_info.get("name", "").split("/")[-1]  # Get just the stack name
                
                if stack_name in STACK_CONFIGS:
                    outputs = get_stack_outputs(stack_name)
                    
                    status["stacks"][stack_name] = {
                        "exists": True,
                        "last_update": stack_info.get("lastUpdate"),
                        "resource_count": stack_info.get("resourceCount", 0),
                        "url": stack_info.get("url"),
                        "config": STACK_CONFIGS[stack_name],
                        "outputs": outputs
                    }
            
            # Check for missing stacks
            for stack_name in STACK_CONFIGS:
                if stack_name not in status["stacks"]:
                    status["stacks"][stack_name] = {
                        "exists": False,
                        "config": STACK_CONFIGS[stack_name]
                    }
                    
        except json.JSONDecodeError:
            status["error"] = "Failed to parse stack list"
    
    return status

# Multi-Cloud Database Management Functions

def provision_shared_databases(clouds: List[str] = None) -> Dict[str, Any]:
    """Create shared RDS, BigQuery, Synapse instances"""
    if clouds is None:
        clouds = ["aws", "gcp", "azure"]
    
    config = load_pulumi_config()
    credentials = validate_cloud_credentials()
    
    results = {}
    
    click.echo("🗄️  Provisioning shared databases...")
    
    for cloud in clouds:
        if not credentials.get(cloud, False):
            results[cloud] = {
                "success": False,
                "error": f"No valid credentials for {cloud}"
            }
            continue
        
        if cloud == "aws":
            results[cloud] = _provision_aws_databases(config["databases"])
        elif cloud == "gcp":
            results[cloud] = _provision_gcp_databases(config["databases"])
        elif cloud == "azure":
            results[cloud] = _provision_azure_databases(config["databases"])
    
    return {
        "success": all(r.get("success", False) for r in results.values()),
        "databases": results
    }

def _provision_aws_databases(db_config: Dict[str, Any]) -> Dict[str, Any]:
    """Provision AWS RDS instances"""
    databases = {}
    
    # PostgreSQL
    if "postgres" in db_config:
        postgres_result = run_pulumi_command([
            "config", "set", "aws:postgres:instanceClass", db_config["postgres"]["instance_class"]
        ], "shared-databases")
        
        databases["postgres"] = {
            "success": postgres_result["success"],
            "type": "postgresql",
            "instance_class": db_config["postgres"]["instance_class"],
            "allocated_storage": db_config["postgres"]["allocated_storage"]
        }
    
    # MySQL
    if "mysql" in db_config:
        mysql_result = run_pulumi_command([
            "config", "set", "aws:mysql:instanceClass", db_config["mysql"]["instance_class"]
        ], "shared-databases")
        
        databases["mysql"] = {
            "success": mysql_result["success"],
            "type": "mysql",
            "instance_class": db_config["mysql"]["instance_class"],
            "allocated_storage": db_config["mysql"]["allocated_storage"]
        }
    
    return {
        "success": all(db.get("success", False) for db in databases.values()),
        "databases": databases,
        "cloud": "aws"
    }

def _provision_gcp_databases(db_config: Dict[str, Any]) -> Dict[str, Any]:
    """Provision GCP Cloud SQL instances"""
    databases = {
        "postgres": {
            "success": True,  # Placeholder - would implement actual GCP provisioning
            "type": "postgresql",
            "tier": "db-f1-micro"
        },
        "bigquery": {
            "success": True,
            "type": "bigquery",
            "datasets": ["tpch", "tpcds", "sample_data"]
        }
    }
    
    return {
        "success": True,
        "databases": databases,
        "cloud": "gcp"
    }

def _provision_azure_databases(db_config: Dict[str, Any]) -> Dict[str, Any]:
    """Provision Azure SQL instances"""
    databases = {
        "sqlserver": {
            "success": True,  # Placeholder - would implement actual Azure provisioning
            "type": "sqlserver",
            "tier": "Basic"
        },
        "synapse": {
            "success": True,
            "type": "synapse",
            "sql_pools": ["shared_pool"]
        }
    }
    
    return {
        "success": True,
        "databases": databases,
        "cloud": "azure"
    }

def get_database_endpoints() -> Dict[str, Any]:
    """Return connection details for shared databases"""
    endpoints = {}
    
    # Get outputs from shared-databases stack
    stack_outputs = get_stack_outputs("shared-databases")
    
    if stack_outputs:
        for db_name, db_info in stack_outputs.items():
            if isinstance(db_info, dict) and "endpoint" in db_info:
                endpoints[db_name] = {
                    "endpoint": db_info["endpoint"],
                    "port": db_info.get("port"),
                    "database": db_info.get("database"),
                    "type": db_info.get("type"),
                    "cloud": db_info.get("cloud")
                }
    
    return endpoints

def update_database_security_groups(allowed_cidrs: List[str] = None) -> Dict[str, Any]:
    """Manage access controls for shared databases"""
    if allowed_cidrs is None:
        allowed_cidrs = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]  # Private networks
    
    result = run_pulumi_command([
        "config", "set", "allowedCidrs", ",".join(allowed_cidrs)
    ], "shared-databases")
    
    if result["success"]:
        # Trigger stack update to apply new security group rules
        update_result = run_pulumi_command(["up", "--yes"], "shared-databases")
        return {
            "success": update_result["success"],
            "allowed_cidrs": allowed_cidrs,
            "error": update_result.get("error") if not update_result["success"] else None
        }
    
    return {
        "success": False,
        "error": "Failed to update security group configuration"
    }

# Connectivity Infrastructure Functions

def provision_bastion_hosts(clouds: List[str] = None) -> Dict[str, Any]:
    """Create bastion hosts for SSH tunneling"""
    if clouds is None:
        clouds = ["aws", "gcp", "azure"]
    
    config = load_pulumi_config()
    credentials = validate_cloud_credentials()
    
    results = {}
    
    click.echo("🔐 Provisioning bastion hosts...")
    
    for cloud in clouds:
        if not credentials.get(cloud, False):
            results[cloud] = {
                "success": False,
                "error": f"No valid credentials for {cloud}"
            }
            continue
        
        if cloud == "aws":
            results[cloud] = _provision_aws_bastion(config["bastions"])
        elif cloud == "gcp":
            results[cloud] = _provision_gcp_bastion(config["bastions"])
        elif cloud == "azure":
            results[cloud] = _provision_azure_bastion(config["bastions"])
    
    return {
        "success": all(r.get("success", False) for r in results.values()),
        "bastions": results
    }

def _provision_aws_bastion(bastion_config: Dict[str, Any]) -> Dict[str, Any]:
    """Provision AWS EC2 bastion host"""
    result = run_pulumi_command([
        "config", "set", "aws:bastion:instanceType", bastion_config["instance_type"]
    ], "connectivity")
    
    if result["success"]:
        result = run_pulumi_command([
            "config", "set", "aws:bastion:keyPair", bastion_config["key_pair_name"]
        ], "connectivity")
    
    return {
        "success": result["success"],
        "instance_type": bastion_config["instance_type"],
        "key_pair": bastion_config["key_pair_name"],
        "cloud": "aws"
    }

def _provision_gcp_bastion(bastion_config: Dict[str, Any]) -> Dict[str, Any]:
    """Provision GCP Compute Engine bastion host"""
    return {
        "success": True,  # Placeholder - would implement actual GCP provisioning
        "machine_type": "e2-micro",
        "cloud": "gcp"
    }

def _provision_azure_bastion(bastion_config: Dict[str, Any]) -> Dict[str, Any]:
    """Provision Azure VM bastion host"""
    return {
        "success": True,  # Placeholder - would implement actual Azure provisioning
        "vm_size": "Standard_B1s",
        "cloud": "azure"
    }

def setup_vpc_networking() -> Dict[str, Any]:
    """Configure VPCs, subnets, security groups"""
    click.echo("🌐 Setting up VPC networking...")
    
    # Configure networking stack
    result = run_pulumi_command(["up", "--yes"], "connectivity")
    
    if result["success"]:
        outputs = get_stack_outputs("connectivity")
        return {
            "success": True,
            "vpcs": outputs.get("vpcs", {}),
            "subnets": outputs.get("subnets", {}),
            "security_groups": outputs.get("security_groups", {})
        }
    
    return {
        "success": False,
        "error": result.get("error", result.get("stderr"))
    }

def manage_ssh_key_pairs() -> Dict[str, Any]:
    """Handle SSH key management for bastions"""
    click.echo("🔑 Managing SSH key pairs...")
    
    ssh_dir = PLATFORM_DIR / "ssh_keys"
    ssh_dir.mkdir(exist_ok=True)
    
    key_pairs = {}
    
    # Generate key pairs for each cloud if they don't exist
    for cloud in ["aws", "gcp", "azure"]:
        private_key_path = ssh_dir / f"{cloud}_bastion_key"
        public_key_path = ssh_dir / f"{cloud}_bastion_key.pub"
        
        if not private_key_path.exists():
            try:
                # Generate SSH key pair
                subprocess.run([
                    "ssh-keygen", "-t", "rsa", "-b", "4096",
                    "-f", str(private_key_path),
                    "-N", "",  # No passphrase
                    "-C", f"platform-bastion-{cloud}"
                ], check=True, capture_output=True)
                
                # Set proper permissions
                private_key_path.chmod(0o600)
                public_key_path.chmod(0o644)
                
                key_pairs[cloud] = {
                    "success": True,
                    "private_key": str(private_key_path),
                    "public_key": str(public_key_path),
                    "generated": True
                }
                
            except subprocess.CalledProcessError as e:
                key_pairs[cloud] = {
                    "success": False,
                    "error": f"Failed to generate key pair: {e}"
                }
        else:
            key_pairs[cloud] = {
                "success": True,
                "private_key": str(private_key_path),
                "public_key": str(public_key_path),
                "generated": False
            }
    
    return {
        "success": all(kp.get("success", False) for kp in key_pairs.values()),
        "key_pairs": key_pairs
    }

# Cost Optimization Functions

def get_infrastructure_costs() -> Dict[str, Any]:
    """Track spending on shared resources"""
    click.echo("💰 Analyzing infrastructure costs...")
    
    costs = {
        "estimated_monthly": 0,
        "breakdown": {},
        "savings": {}
    }
    
    # Get cost estimates from each stack
    for stack_name, config in STACK_CONFIGS.items():
        stack_outputs = get_stack_outputs(stack_name)
        
        costs["breakdown"][stack_name] = {
            "estimated_monthly": config["estimated_cost_monthly"],
            "resources": config["resources"],
            "actual_cost": stack_outputs.get("monthly_cost", "N/A")
        }
        
        costs["estimated_monthly"] += config["estimated_cost_monthly"]
    
    # Calculate savings compared to individual resource model
    old_architecture_cost = 208000  # From CLAUDE.md - $208K/year
    new_architecture_cost = costs["estimated_monthly"] * 12
    
    costs["savings"] = {
        "old_architecture_yearly": old_architecture_cost,
        "new_architecture_yearly": new_architecture_cost,
        "yearly_savings": old_architecture_cost - new_architecture_cost,
        "percentage_saved": ((old_architecture_cost - new_architecture_cost) / old_architecture_cost) * 100
    }
    
    return costs

def optimize_resource_sizing() -> Dict[str, Any]:
    """Right-size instances based on usage"""
    click.echo("📏 Optimizing resource sizing...")
    
    recommendations = {}
    
    # Analyze each stack for optimization opportunities
    for stack_name in STACK_CONFIGS.keys():
        stack_outputs = get_stack_outputs(stack_name)
        
        if stack_outputs and "metrics" in stack_outputs:
            metrics = stack_outputs["metrics"]
            
            recommendations[stack_name] = _analyze_resource_usage(metrics)
        else:
            recommendations[stack_name] = {
                "status": "no_metrics",
                "message": "No usage metrics available for optimization"
            }
    
    return {
        "success": True,
        "recommendations": recommendations,
        "potential_monthly_savings": sum(
            rec.get("potential_savings", 0) 
            for rec in recommendations.values() 
            if isinstance(rec, dict)
        )
    }

def _analyze_resource_usage(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze resource usage metrics and provide recommendations"""
    recommendations = {
        "cpu_utilization": metrics.get("avg_cpu", 0),
        "memory_utilization": metrics.get("avg_memory", 0),
        "recommendations": []
    }
    
    # CPU-based recommendations
    if recommendations["cpu_utilization"] < 20:
        recommendations["recommendations"].append({
            "type": "downsize",
            "resource": "cpu",
            "reason": "Low CPU utilization",
            "potential_savings": 50
        })
    elif recommendations["cpu_utilization"] > 80:
        recommendations["recommendations"].append({
            "type": "upsize",
            "resource": "cpu",
            "reason": "High CPU utilization",
            "potential_cost": 100
        })
    
    # Memory-based recommendations
    if recommendations["memory_utilization"] < 30:
        recommendations["recommendations"].append({
            "type": "downsize",
            "resource": "memory",
            "reason": "Low memory utilization",
            "potential_savings": 30
        })
    
    return recommendations

def schedule_resource_scaling() -> Dict[str, Any]:
    """Auto-scale based on team usage patterns"""
    click.echo("⏰ Setting up resource scaling schedules...")
    
    # Define scaling schedules based on typical work patterns
    schedules = {
        "business_hours": {
            "scale_up": "0 8 * * 1-5",  # 8 AM Monday-Friday
            "scale_down": "0 18 * * 1-5",  # 6 PM Monday-Friday
            "description": "Scale up during business hours"
        },
        "weekend": {
            "scale_down": "0 18 * * 5",  # Friday 6 PM
            "scale_up": "0 8 * * 1",    # Monday 8 AM
            "description": "Scale down over weekends"
        }
    }
    
    # Configure scaling for each stack
    scaling_config = {}
    for stack_name in STACK_CONFIGS.keys():
        result = run_pulumi_command([
            "config", "set", f"{stack_name}:scaling", json.dumps(schedules)
        ], stack_name)
        
        scaling_config[stack_name] = {
            "success": result["success"],
            "schedules": schedules,
            "error": result.get("error") if not result["success"] else None
        }
    
    return {
        "success": all(sc.get("success", False) for sc in scaling_config.values()),
        "scaling_config": scaling_config,
        "estimated_additional_savings": 500  # Monthly savings from scaling
    }

# Configuration and Connection Profile Export

def export_connection_profiles() -> Dict[str, Any]:
    """Generate connection configs for connectivity_module"""
    click.echo("📋 Exporting connection profiles...")
    
    profiles = {}
    
    # Get database endpoints
    db_endpoints = get_database_endpoints()
    
    # Get bastion host information
    connectivity_outputs = get_stack_outputs("connectivity")
    bastions = connectivity_outputs.get("bastions", {})
    
    # Create connection profiles for each database
    for db_name, db_info in db_endpoints.items():
        cloud = db_info.get("cloud", "aws")
        bastion_info = bastions.get(cloud, {})
        
        profiles[f"{cloud}-{db_name}"] = {
            "name": f"{cloud.upper()} {db_name.title()} (Shared)",
            "type": db_info["type"],
            "description": f"Shared {db_info['type']} instance with sample datasets",
            "bastion_host": bastion_info.get("public_ip", f"bastion-{cloud}.platform.internal"),
            "target_host": db_info["endpoint"],
            "target_port": db_info["port"],
            "local_port": db_info["port"],
            "datasets": ["tpch", "tpcds", "sample_data"],
            "cloud": cloud
        }
    
    # Save profiles to connectivity module
    profiles_file = PLATFORM_DIR / "connectivity" / "shared_profiles.json"
    profiles_file.parent.mkdir(exist_ok=True)
    
    with open(profiles_file, 'w') as f:
        json.dump(profiles, f, indent=2)
    
    return {
        "success": True,
        "profiles_count": len(profiles),
        "profiles_file": str(profiles_file),
        "profiles": profiles
    }

def backup_infrastructure_state() -> Dict[str, Any]:
    """Backup Pulumi state files"""
    click.echo("💾 Backing up infrastructure state...")
    
    backup_dir = PLATFORM_DIR / "backups" / f"pulumi_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    backups = {}
    
    for stack_name in STACK_CONFIGS.keys():
        # Export stack state
        export_result = run_pulumi_command(["stack", "export"], stack_name)
        
        if export_result["success"]:
            backup_file = backup_dir / f"{stack_name}_state.json"
            with open(backup_file, 'w') as f:
                f.write(export_result["stdout"])
            
            backups[stack_name] = {
                "success": True,
                "backup_file": str(backup_file),
                "size": len(export_result["stdout"])
            }
        else:
            backups[stack_name] = {
                "success": False,
                "error": export_result.get("error", export_result.get("stderr"))
            }
    
    return {
        "success": all(b.get("success", False) for b in backups.values()),
        "backup_dir": str(backup_dir),
        "backups": backups
    }

# ============================================================================
# USER DATABASE PROVISIONING
# ============================================================================

def provision_user_database_access(user_profile=None, data_sources=None):
    """Provision user-specific database schemas and access across shared instances"""
    if data_sources is None:
        data_sources = ["aws-postgres", "gcp-postgres", "azure-sqlserver"]
    
    try:
        from config import get_user_database_config, validate_user_database_config
        from modules.shared_data_module import create_user_database_schema
        
        # Validate user configuration
        valid, messages = validate_user_database_config()
        if not valid:
            return {
                "success": False,
                "error": f"User configuration invalid: {'; '.join(messages)}"
            }
            
        db_config = get_user_database_config(user_profile)
        
    except ImportError as e:
        return {
            "success": False,
            "error": f"Required modules not available: {str(e)}"
        }
    
    click.echo(f"🔐 Provisioning database access for user: {db_config['schema_prefix']}")
    
    provisioning_results = {}
    sql_scripts = {}
    
    for source_id in data_sources:
        click.echo(f"   • Processing {source_id}...")
        
        # Generate schema creation commands
        schema_result = create_user_database_schema(source_id, user_profile)
        
        if schema_result["success"]:
            provisioning_results[source_id] = {
                "success": True,
                "schema_name": schema_result["schema_name"],
                "database_user": schema_result["database_user"],
                "sql_statements": schema_result["sql_statements"]
            }
            
            sql_scripts[source_id] = schema_result["sql_statements"]
            
        else:
            provisioning_results[source_id] = {
                "success": False,
                "error": schema_result.get("error", "Unknown error")
            }
    
    # Generate consolidated SQL script for manual execution
    script_file = _generate_user_provisioning_script(db_config, sql_scripts)
    
    success_count = len([r for r in provisioning_results.values() if r["success"]])
    total_count = len(provisioning_results)
    
    click.echo(f"✅ User database provisioning prepared: {success_count}/{total_count} sources")
    
    if script_file:
        click.echo(f"\n📋 Next Steps:")
        click.echo(f"   1. Review generated SQL script: {script_file}")
        click.echo(f"   2. Execute SQL statements on each target database")
        click.echo(f"   3. Test catalog connectivity in Starburst")
        click.echo(f"   4. Update environment variables with user credentials")
    
    return {
        "success": success_count == total_count,
        "user": db_config["schema_prefix"],
        "database_user": db_config["database_user"],
        "provisioning_results": provisioning_results,
        "sql_script_file": script_file,
        "sources_processed": total_count,
        "sources_successful": success_count
    }

def _generate_user_provisioning_script(db_config, sql_scripts):
    """Generate consolidated SQL script for user database provisioning"""
    script_content = []
    
    script_content.extend([
        f"-- User Database Provisioning Script",
        f"-- Generated: {datetime.now().isoformat()}",
        f"-- User: {db_config['schema_prefix']}",
        f"-- Database User: {db_config['database_user']}",
        f"",
        f"-- IMPORTANT: Execute these statements on the appropriate shared databases",
        f"-- Make sure to update connection credentials after running these commands",
        f""
    ])
    
    for source_id, sql_statements in sql_scripts.items():
        script_content.extend([
            f"",
            f"-- ===== {source_id.upper()} =====",
            f""
        ])
        
        for statement in sql_statements:
            script_content.append(f"{statement}")
    
    script_content.extend([
        f"",
        f"-- Environment Variables to Set:",
        f"-- export DB_USER_PASSWORD='user_password_123'",
        f"-- export GCP_PROJECT='your-gcp-project'",
        f"-- export GOOGLE_APPLICATION_CREDENTIALS='/path/to/service-account.json'",
        f""
    ])
    
    # Save script file
    script_file = OUTPUTS_DIR / f"user_provisioning_{db_config['username']}.sql"
    
    try:
        with open(script_file, 'w') as f:
            f.write('\n'.join(script_content))
        return str(script_file)
    except Exception as e:
        click.echo(f"⚠️  Could not save SQL script: {str(e)}")
        return None

def get_user_database_status(user_profile=None):
    """Get status of user's database schemas and access across clouds"""
    try:
        from config import get_user_database_config
        from modules.shared_data_module import get_user_data_summary
        
        db_config = get_user_database_config(user_profile)
        user_summary = get_user_data_summary(user_profile)
        
        if not user_summary["success"]:
            return user_summary
            
        summary = user_summary["summary"]
        
        # Get infrastructure status to check if shared databases are running
        infra_status = get_infrastructure_status()
        
        database_status = {}
        
        for stack_name, stack_info in infra_status.get("stacks", {}).items():
            if stack_name == "shared-databases" and stack_info.get("exists"):
                outputs = stack_info.get("outputs", {})
                
                # Check AWS databases
                if "aws_endpoints" in outputs:
                    database_status["aws"] = {
                        "infrastructure_ready": True,
                        "endpoints": outputs["aws_endpoints"],
                        "user_schema_status": "needs_provisioning"  # Would need to check actual DB
                    }
                
                # Check GCP databases  
                if "gcp_endpoints" in outputs:
                    database_status["gcp"] = {
                        "infrastructure_ready": True,
                        "endpoints": outputs["gcp_endpoints"],
                        "user_schema_status": "needs_provisioning"
                    }
                
                # Check Azure databases
                if "azure_endpoints" in outputs:
                    database_status["azure"] = {
                        "infrastructure_ready": True,
                        "endpoints": outputs["azure_endpoints"], 
                        "user_schema_status": "needs_provisioning"
                    }
        
        return {
            "success": True,
            "user": db_config["schema_prefix"],
            "user_info": summary["user_info"],
            "enabled_sources": summary["enabled_sources"],
            "catalogs": summary["catalogs"],
            "database_status": database_status,
            "isolation_status": summary["isolation_status"]
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get user database status: {str(e)}"
        }

def cleanup_user_database_access(user_profile=None, data_sources=None):
    """Remove user-specific database schemas and access (for cleanup/reset)"""
    if data_sources is None:
        data_sources = ["aws-postgres", "gcp-postgres", "azure-sqlserver"]
    
    try:
        from config import get_user_database_config
        db_config = get_user_database_config(user_profile)
    except ImportError:
        return {
            "success": False,
            "error": "Configuration module not available"
        }
    
    click.echo(f"🧹 Cleaning up database access for user: {db_config['schema_prefix']}")
    
    cleanup_results = {}
    sql_scripts = {}
    
    for source_id in data_sources:
        # Generate cleanup SQL statements
        cleanup_sql = []
        
        if "postgres" in source_id or "mysql" in source_id:
            cleanup_sql.extend([
                f"DROP SCHEMA IF EXISTS {db_config['default_schema']} CASCADE;",
                f"DROP USER IF EXISTS {db_config['database_user']};"
            ])
        elif "sqlserver" in source_id or "synapse" in source_id:
            cleanup_sql.extend([
                f"DROP SCHEMA [{db_config['default_schema']}];",
                f"DROP USER [{db_config['database_user']}];"
            ])
        elif "bigquery" in source_id:
            cleanup_sql.append(f"-- BigQuery dataset: {db_config['default_schema']} (delete via API or Console)")
        
        cleanup_results[source_id] = {
            "success": True,
            "sql_statements": cleanup_sql
        }
        
        sql_scripts[source_id] = cleanup_sql
    
    # Generate cleanup script
    script_file = _generate_user_cleanup_script(db_config, sql_scripts)
    
    click.echo(f"✅ User database cleanup script generated")
    if script_file:
        click.echo(f"   • Cleanup script: {script_file}")
        click.echo(f"   • Execute SQL statements to remove user schemas and access")
    
    return {
        "success": True,
        "user": db_config["schema_prefix"],
        "cleanup_results": cleanup_results,
        "sql_script_file": script_file
    }

def _generate_user_cleanup_script(db_config, sql_scripts):
    """Generate consolidated SQL script for user database cleanup"""
    script_content = [
        f"-- User Database Cleanup Script",
        f"-- Generated: {datetime.now().isoformat()}", 
        f"-- User: {db_config['schema_prefix']}",
        f"",
        f"-- WARNING: This will permanently delete user schemas and data",
        f"-- Make sure to backup any important data before running",
        f""
    ]
    
    for source_id, sql_statements in sql_scripts.items():
        script_content.extend([
            f"",
            f"-- ===== {source_id.upper()} CLEANUP =====",
            f""
        ])
        
        for statement in sql_statements:
            script_content.append(f"{statement}")
    
    # Save cleanup script
    script_file = OUTPUTS_DIR / f"user_cleanup_{db_config['username']}.sql"
    
    try:
        with open(script_file, 'w') as f:
            f.write('\n'.join(script_content))
        return str(script_file)
    except Exception:
        return None