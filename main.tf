terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "4.25.0"
    }
  }
}

provider "azurerm" {
  features {
  }
  subscription_id = "7a3648e3-dcae-422f-867c-4396fe4c3334"
}

resource "random_integer" "randomint" {
  min = 10000
  max = 99999
}

resource "azurerm_resource_group" "arg" {
  name     = "${var.resource_group_name}_${random_integer.randomint.result}"
  location = var.resource_group_location
}

resource "azurerm_service_plan" "asp" {
  name                = "${var.app_service_plan_name}_${random_integer.randomint.result}"
  resource_group_name = azurerm_resource_group.arg.name
  location            = azurerm_resource_group.arg.location
  os_type             = "Linux"
  sku_name            = "F1"
}

resource "azurerm_linux_web_app" "alwa" {
  name                = var.app_service_name
  resource_group_name = azurerm_resource_group.arg.name
  location            = azurerm_resource_group.arg.location
  service_plan_id     = azurerm_service_plan.asp.id

  site_config {
    application_stack {
      dotnet_version = "6.0"
    }
    always_on = false
  }
  connection_string {
    name  = "DefaultConnection"
    type  = "SQLAzure"
    value = "Data Source=tcp:${azurerm_mssql_server.mssqlserver.fully_qualified_domain_name},1433;Initial Catalog=${azurerm_mssql_database.mssqlserverdb.name};User ID=${azurerm_mssql_server.mssqlserver.id};Password=${azurerm_mssql_server.mssqlserver.administrator_login_password};Trusted_Connection=False; MultipleActiveResultSets=True;"
  }
}


resource "azurerm_mssql_server" "mssqlserver" {
  name                         = var.sql_server_name
  resource_group_name          = azurerm_resource_group.arg.name
  location                     = azurerm_resource_group.arg.location
  version                      = "12.0"
  administrator_login          = var.sql_admin_login
  administrator_login_password = var.sql_admin_password
}

resource "azurerm_mssql_database" "mssqlserverdb" {
  name                 = "${var.sql_database_name}_${random_integer.randomint.result}"
  server_id            = azurerm_mssql_server.mssqlserver.id
  collation            = "SQL_Latin1_General_CP1_CI_AS"
  license_type         = "LicenseIncluded"
  max_size_gb          = 2
  sku_name             = "S0"
  zone_redundant       = false
  storage_account_type = "Zone"
  geo_backup_enabled   = false
}

resource "azurerm_mssql_firewall_rule" "firewall" {
  name             = var.firewall_rule_name
  server_id        = azurerm_mssql_server.mssqlserver.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_app_service_source_control" "github" {
  app_id                 = azurerm_linux_web_app.alwa.id
  repo_url               = var.repo_URL
  branch                 = "main"
  use_manual_integration = true
}