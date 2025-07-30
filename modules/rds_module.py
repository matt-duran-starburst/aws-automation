"""
RDS database management module for the Platform CLI tool.
Supports PostgreSQL, MySQL, and Oracle database creation and management.
"""

import click
import json
import boto3
from botocore.exceptions import ClientError


# Database engine configurations
DATABASE_ENGINES = {
    "postgres": {
        "engine": "postgres",
        "port": 5432,
        "default_db": "postgres",
        "default_instance": "db.t3.micro",
        "parameter_group_family": "postgres15"
    },
    "mysql": {
        "engine": "mysql",
        "port": 3306,
        "default_db": "mysql",
        "default_instance": "db.t3.micro",
        "parameter_group_family": "mysql8.0"
    },
    "oracle": {
        "engine": "oracle-ee",
        "port": 1521,
        "default_db": "ORCL",
        "default_instance": "db.t3.small",  # Oracle requires larger instance
        "parameter_group_family": "oracle-ee-19"
    }
}


def create_rds_security_group(name, vpc_id, port, region, deployment_id=None):
    """Create a security group for RDS database"""
    try:
        ec2 = boto3.client('ec2', region_name=region)

        # Create a security group for RDS
        sg_name = f"{name}-rds-sg"
        sg_desc = f"Security group for RDS database {name}"

        click.echo(f"📊 Creating security group: {sg_name}")
        sg_response = ec2.create_security_group(
            GroupName=sg_name,
            Description=sg_desc,
            VpcId=vpc_id
        )
        sg_id = sg_response['GroupId']

        # Tag the security group
        ec2.create_tags(
            Resources=[sg_id],
            Tags=[
                {'Key': 'Name', 'Value': sg_name},
                {'Key': 'PlatformManaged', 'Value': 'true'},
                {'Key': 'DeploymentId', 'Value': deployment_id or name}
            ]
        )

        # Allow database traffic from the VPC CIDR
        vpc_response = ec2.describe_vpcs(VpcIds=[vpc_id])
        vpc_cidr = vpc_response['Vpcs'][0]['CidrBlock']

        ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {
                    'IpProtocol': 'tcp',
                    'FromPort': port,
                    'ToPort': port,
                    'IpRanges': [{'CidrIp': vpc_cidr}]
                }
            ]
        )

        return sg_id

    except Exception as e:
        raise Exception(f"Failed to create security group: {str(e)}")


def create_db_subnet_group(name, subnets, region, deployment_id=None):
    """Create a DB subnet group for RDS"""
    try:
        rds = boto3.client('rds', region_name=region)

        # Get subnet IDs
        subnet_ids = [subnet['id'] for subnet in subnets]

        # Create subnet group for RDS
        db_subnet_group_name = f"{name}-subnet-group"
        click.echo(f"📊 Creating DB subnet group: {db_subnet_group_name}")

        rds.create_db_subnet_group(
            DBSubnetGroupName=db_subnet_group_name,
            DBSubnetGroupDescription=f"Subnet group for {name}",
            SubnetIds=subnet_ids,
            Tags=[
                {'Key': 'Name', 'Value': db_subnet_group_name},
                {'Key': 'PlatformManaged', 'Value': 'true'},
                {'Key': 'DeploymentId', 'Value': deployment_id or name}
            ]
        )

        return db_subnet_group_name

    except Exception as e:
        raise Exception(f"Failed to create DB subnet group: {str(e)}")


def create_rds_instance(name, engine, vpc_id, subnets, region, username, password,
                       db_name=None, instance_type=None, allocated_storage=20,
                       backup_retention=7, deployment_id=None):
    """Create an RDS database instance with specified engine"""

    if engine not in DATABASE_ENGINES:
        raise ValueError(f"Unsupported database engine: {engine}. Supported engines: {list(DATABASE_ENGINES.keys())}")

    engine_config = DATABASE_ENGINES[engine]

    try:
        click.echo(f"🔄 Creating {engine.upper()} RDS instance: {name}...")

        # Create an RDS client
        rds = boto3.client('rds', region_name=region)

        # Use default values if not provided
        if not db_name:
            db_name = engine_config["default_db"]
        if not instance_type:
            instance_type = engine_config["default_instance"]

        # Sanitize database name based on engine requirements
        if engine == "postgres":
            db_name_sanitized = db_name.replace("-", "_")
        elif engine == "mysql":
            db_name_sanitized = db_name.replace("-", "_")
        elif engine == "oracle":
            # Oracle uses SID, has different naming requirements
            db_name_sanitized = db_name.upper()[:8]  # Oracle SID max 8 chars

        # Create security group
        sg_id = create_rds_security_group(
            name, vpc_id, engine_config["port"], region, deployment_id
        )

        # Create subnet group
        db_subnet_group_name = create_db_subnet_group(
            name, subnets, region, deployment_id
        )

        # Create the RDS instance
        click.echo(f"🚀 Launching {engine.upper()} RDS instance: {name} ({instance_type}, {allocated_storage}GB)")

        # Base parameters for RDS instance
        create_params = {
            'DBInstanceIdentifier': name,
            'AllocatedStorage': allocated_storage,
            'DBInstanceClass': instance_type,
            'Engine': engine_config["engine"],
            'MasterUsername': username,
            'MasterUserPassword': password,
            'VpcSecurityGroupIds': [sg_id],
            'DBSubnetGroupName': db_subnet_group_name,
            'BackupRetentionPeriod': backup_retention,
            'MultiAZ': False,
            'AutoMinorVersionUpgrade': True,
            'PubliclyAccessible': False,
            'Tags': [
                {'Key': 'Name', 'Value': name},
                {'Key': 'PlatformManaged', 'Value': 'true'},
                {'Key': 'DeploymentId', 'Value': deployment_id or name},
                {'Key': 'Engine', 'Value': engine}
            ]
        }

        # Add database name only for PostgreSQL and MySQL (Oracle uses different approach)
        if engine in ["postgres", "mysql"]:
            create_params['DBName'] = db_name_sanitized

        # Oracle-specific configurations
        if engine == "oracle":
            create_params.update({
                'LicenseModel': 'bring-your-own-license',  # or 'license-included'
                'StorageEncrypted': True,  # Recommended for Oracle
                'AllocatedStorage': max(allocated_storage, 20),  # Oracle minimum is 20GB
            })

        response = rds.create_db_instance(**create_params)

        click.echo(f"✅ RDS instance creation initiated. This may take 5-15 minutes to complete.")
        click.echo(f"📊 Database endpoint will be available when the instance is ready.")

        return {
            "db_instance_id": name,
            "security_group_id": sg_id,
            "subnet_group": db_subnet_group_name,
            "status": "creating",
            "db_name": db_name_sanitized,
            "username": username,
            "engine": engine_config["engine"],
            "port": engine_config["port"],
            "instance_type": instance_type,
            "allocated_storage": allocated_storage,
            "region": region
        }

    except Exception as e:
        click.echo(f"❌ Failed to create RDS instance: {str(e)}")
        raise


def get_rds_instance_status(instance_id, region):
    """Get the status and endpoint information for an RDS instance"""
    try:
        rds = boto3.client('rds', region_name=region)
        response = rds.describe_db_instances(DBInstanceIdentifier=instance_id)

        if not response['DBInstances']:
            return None

        instance = response['DBInstances'][0]
        return {
            "status": instance['DBInstanceStatus'],
            "endpoint": instance.get('Endpoint', {}).get('Address'),
            "port": instance.get('Endpoint', {}).get('Port'),
            "engine": instance['Engine'],
            "engine_version": instance['EngineVersion'],
            "storage": instance['AllocatedStorage'],
            "instance_class": instance['DBInstanceClass'],
            "availability_zone": instance.get('AvailabilityZone'),
            "vpc_id": instance.get('DBSubnetGroup', {}).get('VpcId'),
            "multi_az": instance.get('MultiAZ', False)
        }
    except Exception as e:
        click.echo(f"❌ Error getting RDS status: {str(e)}")
        return None


def delete_rds_instance(instance_id, region, skip_final_snapshot=True, final_snapshot_id=None):
    """Delete an RDS instance"""
    try:
        rds = boto3.client('rds', region_name=region)

        delete_params = {
            'DBInstanceIdentifier': instance_id,
            'SkipFinalSnapshot': skip_final_snapshot
        }

        if not skip_final_snapshot and final_snapshot_id:
            delete_params['FinalDBSnapshotIdentifier'] = final_snapshot_id

        response = rds.delete_db_instance(**delete_params)

        click.echo(f"✅ RDS instance deletion initiated: {instance_id}")
        return True

    except Exception as e:
        click.echo(f"❌ Failed to delete RDS instance: {str(e)}")
        return False


def get_connection_string(db_info, password):
    """Generate connection strings for different database engines"""
    endpoint = db_info.get('endpoint')
    port = db_info.get('port')
    username = db_info.get('username')
    db_name = db_info.get('db_name')
    engine = db_info.get('engine')

    if not endpoint:
        return "Database endpoint not yet available"

    connection_strings = {}

    if engine == "postgres":
        connection_strings['psql'] = f"psql -h {endpoint} -p {port} -U {username} -d {db_name}"
        connection_strings['url'] = f"postgresql://{username}:{password}@{endpoint}:{port}/{db_name}"
        connection_strings['jdbc'] = f"jdbc:postgresql://{endpoint}:{port}/{db_name}"

    elif engine == "mysql":
        connection_strings['mysql'] = f"mysql -h {endpoint} -P {port} -u {username} -p"
        connection_strings['url'] = f"mysql://{username}:{password}@{endpoint}:{port}/{db_name}"
        connection_strings['jdbc'] = f"jdbc:mysql://{endpoint}:{port}/{db_name}"

    elif engine.startswith("oracle"):
        connection_strings['sqlplus'] = f"sqlplus {username}/{password}@{endpoint}:{port}/{db_name}"
        connection_strings['url'] = f"oracle://{username}:{password}@{endpoint}:{port}/{db_name}"
        connection_strings['jdbc'] = f"jdbc:oracle:thin:@{endpoint}:{port}:{db_name}"

    return connection_strings


def validate_engine_requirements(engine, instance_type, allocated_storage):
    """Validate engine-specific requirements"""
    if engine not in DATABASE_ENGINES:
        raise ValueError(f"Unsupported engine: {engine}")

    engine_config = DATABASE_ENGINES[engine]

    # Oracle-specific validations
    if engine == "oracle":
        if allocated_storage < 20:
            raise ValueError("Oracle requires minimum 20GB storage")
        if instance_type.startswith("db.t2.") or instance_type.startswith("db.t3.micro"):
            raise ValueError("Oracle requires at least db.t3.small instance type")

    # MySQL and PostgreSQL are more flexible
    if engine in ["postgres", "mysql"]:
        if allocated_storage < 20:
            click.echo("⚠️ Warning: Storage less than 20GB may affect performance")

    return True