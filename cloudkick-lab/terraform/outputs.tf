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

output "AccessLogsBucket" {
  value = aws_s3_bucket.access_logs.id
}

output "StateTable" {
  value = aws_dynamodb_table.state.name
}

output "ActionRole" {
  value = var.mode == "vulnerable" ? aws_iam_role.worker.name : aws_iam_role.action.name
}

output "AgentExecutionRole" {
  value = aws_iam_role.worker.name
}

output "BedrockAgentId" {
  value = var.engine == "classic" ? aws_bedrockagent_agent.kickassist[0].agent_id : ""
}

output "BedrockAgentArn" {
  value = var.engine == "classic" ? aws_bedrockagent_agent.kickassist[0].agent_arn : ""
}

output "BedrockAgentAliasId" {
  value = var.engine == "classic" ? aws_bedrockagent_agent_alias.demo[0].agent_alias_id : ""
}

output "BedrockActionGroupId" {
  value = var.engine == "classic" ? aws_bedrockagent_agent_action_group.tools[0].action_group_id : ""
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

output "Engine" {
  value = var.engine
}
