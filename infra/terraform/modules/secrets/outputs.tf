output "secret_arn" {
  description = "ARN of the Secrets Manager secret. CI uses this to fetch the env blob."
  value       = aws_secretsmanager_secret.app.arn
}
