# Hetzner Cloud VPS that runs the ZapAgent stack via Docker Compose.
# cloud-init bootstraps Docker, pulls the repo, and brings the stack up.

terraform {
  required_version = ">= 1.6"
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.48"
    }
  }
}

resource "hcloud_ssh_key" "ops" {
  name       = "${var.environment}-zapagent-ops"
  public_key = var.ssh_public_key
}

resource "hcloud_firewall" "stack" {
  name = "${var.environment}-zapagent-fw"

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "22"
    source_ips = var.ssh_allowed_cidrs
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "80"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_server" "stack" {
  name        = "${var.environment}-zapagent"
  server_type = var.server_type
  image       = "ubuntu-24.04"
  location    = var.location
  ssh_keys    = [hcloud_ssh_key.ops.id]

  firewall_ids = [hcloud_firewall.stack.id]

  user_data = templatefile("${path.module}/cloud-init.yaml.tpl", {
    repo_url    = var.repo_url
    git_ref     = var.git_ref
    env_blob    = var.env_blob
    domain_name = var.domain_name
  })

  labels = {
    project     = "zapagent"
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "hcloud_volume" "data" {
  name     = "${var.environment}-zapagent-data"
  size     = var.data_volume_size_gb
  location = var.location
  format   = "ext4"
}

resource "hcloud_volume_attachment" "data" {
  volume_id = hcloud_volume.data.id
  server_id = hcloud_server.stack.id
  automount = true
}
