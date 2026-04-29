output "server_id" {
  description = "Hetzner server id."
  value       = hcloud_server.stack.id
}

output "ipv4_address" {
  description = "Public IPv4 of the VPS."
  value       = hcloud_server.stack.ipv4_address
}

output "ipv6_address" {
  description = "Public IPv6 of the VPS."
  value       = hcloud_server.stack.ipv6_address
}
