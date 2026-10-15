output "ApiUrl" {
  value = "https://${aws_api_gateway_rest_api.this.id}.execute-api.${var.aws_region}.amazonaws.com/${aws_api_gateway_stage.lab.stage_name}/"
}

output "OrdersBucket" {
  value = aws_s3_bucket.orders.id
}

output "PrivateBucket" {
  value = aws_s3_bucket.private.id
}

output "AuditBucket" {
  value = aws_s3_bucket.audit.id
}

output "StateTable" {
  value = aws_dynamodb_table.state.name
}

output "ActionRole" {
  value = aws_iam_role.action.name
}

output "ActionFunction" {
  value = aws_lambda_function.action.function_name
}

output "WorkerFunction" {
  value = aws_lambda_function.worker.function_name
}

output "BridgeFunction" {
  value = aws_lambda_function.bridge.function_name
}

output "FailureQueueUrl" {
  value = aws_sqs_queue.worker_failures.url
}

output "BuildSha" {
  value = var.build_sha
}

output "Mode" {
  value = var.mode
}
