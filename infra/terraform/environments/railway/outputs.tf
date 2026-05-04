output "api_url" {
  description = "Public URL for the FastAPI service"
  value       = "https://${railway_service.api.default_domain}"
}

output "evolution_url" {
  description = "Public URL for the Evolution API service"
  value       = "https://${railway_service.evolution.default_domain}"
}

output "redis_url" {
  description = "Redis connection string (internal to Railway)"
  value       = railway_plugin.redis.url
  sensitive   = true
}

output "project_id" {
  description = "Railway project ID"
  value       = railway_project.zapagent.id
}
