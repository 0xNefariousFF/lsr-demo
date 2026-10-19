data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  partition = data.aws_partition.current.partition
  region    = var.aws_region
  names = {
    action      = "${var.name}-agent-tools"
    agent       = "${var.name}-kickassist"
    bridge      = "${var.name}-bridge"
    worker      = "${var.name}-worker"
    state       = "${var.name}-state"
    trail       = "${var.name}-object-evidence"
    api         = "${var.name}-api"
    orders      = "${var.name}-${var.account_id}-${var.aws_region}-orders"
    private     = "${var.name}-${var.account_id}-${var.aws_region}-private"
    audit       = "${var.name}-${var.account_id}-${var.aws_region}-audit"
    access_logs = "${var.name}-${var.account_id}-${var.aws_region}-access-logs"
  }
  tags = {
    # AWS S3 objects accept at most ten tags. These provider defaults also apply
    # to the Lambda deployment ZIP, so keep this shared set at ten or fewer.
    Project         = "CloudKick"
    Environment     = "isolated-lab"
    LabName         = var.name
    LabMode         = var.mode
    Owner           = var.owner
    ExpiresAt       = tostring(var.expires_epoch)
    ManagedBy       = "Terraform"
    DataContext     = "synthetic-demo-only"
    SecurityProfile = var.mode == "vulnerable" ? "intentional-graph-demo" : "remediated-comparison"
    AgentEngine     = var.engine
  }
  lambda_environment = {
    STATE_TABLE = local.names.state
    LAB_MODE    = var.mode
    ENGINE      = var.engine
    LAB_EXPIRES = tostring(var.expires_epoch)
    BUILD_SHA   = var.build_sha
  }
}

resource "terraform_data" "account_guard" {
  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.account_id
      error_message = "The active AWS identity does not belong to the explicitly configured isolated lab account."
    }
  }
}

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/cloudkick-lambda.zip"
  excludes    = ["__pycache__", "__pycache__/*", "*.pyc"]
}

# Upload Lambda code through S3 instead of embedding the ZIP in the
# UpdateFunctionCode request. This avoids an AWS provider serialization failure
# ("bufio.Scanner: token too long") with binary inline payloads.
resource "aws_s3_object" "lambda_package" {
  bucket      = aws_s3_bucket.orders.id
  key         = "artifacts/cloudkick-lambda.zip"
  source      = data.archive_file.lambda.output_path
  source_hash = data.archive_file.lambda.output_base64sha256
}

resource "aws_dynamodb_table" "state" {
  name         = local.names.state
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  ttl {
    attribute_name = "expiry"
    enabled        = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_s3_bucket" "orders" {
  bucket        = local.names.orders
  force_destroy = true
}

resource "aws_s3_bucket" "private" {
  bucket        = local.names.private
  force_destroy = true

  tags = {
    DemoPath            = "CloudKickAgentKillChain"
    KillChainStage      = "CollectionTarget"
    AIComponent         = "AgentDataSource"
    DataClassification  = "ConfidentialSyntheticCustomerRecords"
    BusinessCriticality = "HighDemoImpact"
    CrownJewel          = "true"
  }
}

resource "aws_s3_bucket" "audit" {
  bucket        = local.names.audit
  force_destroy = true

  tags = {
    DemoPath       = "CloudKickAgentKillChain"
    KillChainStage = "Evidence"
  }
}

resource "aws_s3_bucket" "access_logs" {
  bucket        = local.names.access_logs
  force_destroy = true

  tags = {
    DemoPath       = "CloudKickAgentKillChain"
    KillChainStage = "Evidence"
  }
}

resource "aws_s3_bucket_public_access_block" "all" {
  for_each = {
    orders  = aws_s3_bucket.orders.id
    private = aws_s3_bucket.private.id
    audit   = aws_s3_bucket.audit.id
    logs    = aws_s3_bucket.access_logs.id
  }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "all" {
  for_each = {
    orders  = aws_s3_bucket.orders.id
    private = aws_s3_bucket.private.id
    audit   = aws_s3_bucket.audit.id
    logs    = aws_s3_bucket.access_logs.id
  }
  bucket = each.value
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "all" {
  for_each = {
    orders  = aws_s3_bucket.orders.id
    private = aws_s3_bucket.private.id
    audit   = aws_s3_bucket.audit.id
    logs    = aws_s3_bucket.access_logs.id
  }
  bucket = each.value
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "orders_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.orders.arn,
      "${aws_s3_bucket.orders.arn}/*"
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

data "aws_iam_policy_document" "private_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.private.arn,
      "${aws_s3_bucket.private.arn}/*"
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

data "aws_iam_policy_document" "audit_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.audit.arn,
      "${aws_s3_bucket.audit.arn}/*"
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "CloudTrailAclCheck"
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.audit.arn]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:cloudtrail:${var.aws_region}:${var.account_id}:trail/${local.names.trail}"]
    }
  }

  statement {
    sid       = "CloudTrailWrite"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.audit.arn}/AWSLogs/${var.account_id}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:cloudtrail:${var.aws_region}:${var.account_id}:trail/${local.names.trail}"]
    }
  }
}

data "aws_iam_policy_document" "access_logs_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.access_logs.arn,
      "${aws_s3_bucket.access_logs.arn}/*"
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "S3ServerAccessLogDelivery"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.access_logs.arn}/audit/AWSLogs/${var.account_id}/*"]
    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.audit.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "orders" {
  bucket = aws_s3_bucket.orders.id
  policy = data.aws_iam_policy_document.orders_bucket.json
}

resource "aws_s3_bucket_policy" "private" {
  bucket = aws_s3_bucket.private.id
  policy = data.aws_iam_policy_document.private_bucket.json
}

resource "aws_s3_bucket_policy" "audit" {
  bucket = aws_s3_bucket.audit.id
  policy = data.aws_iam_policy_document.audit_bucket.json
}

resource "aws_s3_bucket_policy" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  policy = data.aws_iam_policy_document.access_logs_bucket.json
}

resource "aws_s3_bucket_logging" "audit" {
  depends_on = [aws_s3_bucket_policy.access_logs]

  bucket        = aws_s3_bucket.audit.id
  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "audit/AWSLogs/${var.account_id}/"
}

resource "aws_cloudtrail" "objects" {
  depends_on                    = [aws_s3_bucket_policy.audit]
  name                          = local.names.trail
  s3_bucket_name                = aws_s3_bucket.audit.id
  enable_logging                = true
  enable_log_file_validation    = true
  include_global_service_events = false
  is_multi_region_trail         = false

  advanced_event_selector {
    name = "CloudKickObjectEvidence"
    field_selector {
      field  = "eventCategory"
      equals = ["Data"]
    }
    field_selector {
      field  = "resources.type"
      equals = ["AWS::S3::Object"]
    }
    field_selector {
      field = "resources.ARN"
      starts_with = [
        "${aws_s3_bucket.orders.arn}/",
        "${aws_s3_bucket.private.arn}/"
      ]
    }
  }
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "bedrock_agent_trust" {
  count = var.engine == "classic" ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:bedrock:${var.aws_region}:${var.account_id}:agent/*"]
    }
  }
}

resource "aws_iam_role" "bridge" {
  name               = "${var.name}-bridge"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json

  tags = {
    DemoPath       = "CloudKickAgentKillChain"
    KillChainStage = "SeparatedIdentity"
    AIComponent    = "RemediatedBridgeIdentity"
  }
}

resource "aws_iam_role" "worker" {
  name               = "${var.name}-worker"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json

  tags = {
    DemoPath       = "CloudKickAgentKillChain"
    KillChainStage = var.mode == "vulnerable" ? "InitialAccessToCollection" : "Discovery"
    AIComponent    = "AgentExecutionIdentity"
    AIService      = var.engine == "classic" ? "AmazonBedrockAgents" : "AmazonBedrockConverse"
    AIToolAccess   = var.mode == "vulnerable" ? "ReturnsAndPrivateArchive" : "BusinessToolsOnly"
  }
}

resource "aws_iam_role" "action" {
  name               = "${var.name}-action"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json

  tags = {
    DemoPath       = "CloudKickAgentKillChain"
    KillChainStage = "SeparatedIdentity"
    AIComponent    = "RemediatedToolIdentity"
  }
}

resource "aws_iam_role" "agent" {
  count = var.engine == "classic" ? 1 : 0

  name               = "${var.name}-bedrock-agent"
  assume_role_policy = data.aws_iam_policy_document.bedrock_agent_trust[0].json

  tags = {
    DemoPath       = "CloudKickAgentKillChain"
    KillChainStage = "AIExecution"
    AIComponent    = "NativeBedrockAgentIdentity"
    AIService      = "AmazonBedrockAgents"
  }
}

data "aws_iam_policy_document" "bridge" {
  statement {
    sid       = "ApplicationLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.bridge.arn}:*"]
  }
  statement {
    sid       = "ScopedState"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.state.arn]
    condition {
      test     = "ForAllValues:StringLike"
      variable = "dynamodb:LeadingKeys"
      values   = ["J#*", "A#*", "R#*"]
    }
  }
  statement {
    sid       = "QueueWorker"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.worker.arn]
  }
}

data "aws_iam_policy_document" "worker" {
  statement {
    sid       = "ApplicationLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.worker.arn}:*"]
  }
  statement {
    sid       = "ScopedState"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.state.arn]
    condition {
      test     = "ForAllValues:StringLike"
      variable = "dynamodb:LeadingKeys"
      values   = ["J#*", "S#*"]
    }
  }
  dynamic "statement" {
    for_each = var.engine == "converse" ? [1] : []
    content {
      sid       = "InvokeSelectedModel"
      actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      resources = var.model_invoke_arns
    }
  }
  dynamic "statement" {
    for_each = var.engine == "converse" ? [1] : []
    content {
      sid       = "InvokeAction"
      actions   = ["lambda:InvokeFunction"]
      resources = [aws_lambda_function.action.arn]
    }
  }
  dynamic "statement" {
    for_each = var.engine == "classic" ? [1] : []
    content {
      sid       = "InvokeNativeAgent"
      actions   = ["bedrock:InvokeAgent"]
      resources = [aws_bedrockagent_agent_alias.demo[0].agent_alias_arn]
    }
  }
  statement {
    sid       = "AsyncFailureDestination"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.worker_failures.arn]
  }
}

data "aws_iam_policy_document" "agent" {
  count = var.engine == "classic" ? 1 : 0

  statement {
    sid       = "InvokeSelectedModelWithoutGuardrail"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = var.model_invoke_arns
  }
}

data "aws_iam_policy_document" "action" {
  statement {
    sid       = "ApplicationLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.action.arn}:*"]
  }
  statement {
    sid       = "ScopedState"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.state.arn]
    condition {
      test     = "ForAllValues:StringLike"
      variable = "dynamodb:LeadingKeys"
      values   = ["A#*", "R#*", "E#*"]
    }
  }
  statement {
    sid     = "BusinessFixtures"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.orders.arn}/orders/*",
      "${aws_s3_bucket.orders.arn}/policies/returns.json"
    ]
  }
  dynamic "statement" {
    for_each = var.mode == "vulnerable" ? [1] : []
    content {
      sid       = "IntentionalOverPermissivePrivateBucketRead"
      actions   = ["s3:GetObject"]
      resources = ["${aws_s3_bucket.private.arn}/*"]
    }
  }
  dynamic "statement" {
    for_each = var.mode == "vulnerable" ? [1] : []
    content {
      sid       = "IntentionalOverPermissivePrivateBucketCatalog"
      actions   = ["s3:ListBucket"]
      resources = [aws_s3_bucket.private.arn]
    }
  }
}

resource "aws_iam_role_policy" "bridge" {
  name   = "CloudKickBridgeScope"
  role   = var.mode == "vulnerable" ? aws_iam_role.worker.id : aws_iam_role.bridge.id
  policy = data.aws_iam_policy_document.bridge.json
}

resource "aws_iam_role_policy" "worker" {
  name   = "CloudKickWorkerScope"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}

resource "aws_iam_role_policy" "action" {
  name   = "CloudKickActionScope"
  role   = var.mode == "vulnerable" ? aws_iam_role.worker.id : aws_iam_role.action.id
  policy = data.aws_iam_policy_document.action.json
}

resource "aws_iam_role_policy" "agent" {
  count = var.engine == "classic" ? 1 : 0

  name   = "CloudKickBedrockAgentScope"
  role   = aws_iam_role.agent[0].id
  policy = data.aws_iam_policy_document.agent[0].json
}

resource "aws_cloudwatch_log_group" "bridge" {
  name              = "/aws/lambda/${local.names.bridge}"
  retention_in_days = 3
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/lambda/${local.names.worker}"
  retention_in_days = 3
}

resource "aws_cloudwatch_log_group" "action" {
  name              = "/aws/lambda/${local.names.action}"
  retention_in_days = 3
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/apigateway/${var.name}"
  retention_in_days = 3
}

resource "aws_sqs_queue" "worker_failures" {
  name                      = "${var.name}-worker-failures"
  message_retention_seconds = 86400
  sqs_managed_sse_enabled   = true
}

resource "aws_lambda_function" "action" {
  depends_on       = [terraform_data.account_guard, aws_cloudwatch_log_group.action]
  function_name    = local.names.action
  s3_bucket        = aws_s3_object.lambda_package.bucket
  s3_key           = aws_s3_object.lambda_package.key
  source_code_hash = data.archive_file.lambda.output_base64sha256
  handler          = "action.handler"
  role             = var.mode == "vulnerable" ? aws_iam_role.worker.arn : aws_iam_role.action.arn
  runtime          = "python3.12"
  memory_size      = 512
  timeout          = 20

  tags = {
    DemoPath       = "CloudKickAgentKillChain"
    KillChainStage = "PrivilegeMisuse"
    AIComponent    = "AgentToolExecutor"
    AIToolNames    = "Returns,HistoricalServiceRecords"
    DataAccess     = var.mode == "vulnerable" ? "PrivateArchive" : "BusinessDataOnly"
  }

  environment {
    variables = merge(local.lambda_environment, {
      CONTEXT_SECRET = var.context_secret
      ORDERS_BUCKET  = aws_s3_bucket.orders.id
      POLICY_BUCKET  = aws_s3_bucket.orders.id
      PRIVATE_BUCKET = aws_s3_bucket.private.id
    })
  }
}

resource "aws_lambda_function" "worker" {
  depends_on       = [terraform_data.account_guard, aws_cloudwatch_log_group.worker]
  function_name    = local.names.worker
  s3_bucket        = aws_s3_object.lambda_package.bucket
  s3_key           = aws_s3_object.lambda_package.key
  source_code_hash = data.archive_file.lambda.output_base64sha256
  handler          = "worker.handler"
  role             = aws_iam_role.worker.arn
  runtime          = "python3.12"
  memory_size      = 512
  timeout          = 240

  tags = {
    DemoPath       = "CloudKickAgentKillChain"
    KillChainStage = "Discovery"
    AIComponent    = "AgentOrchestrator"
    AIService      = var.engine == "classic" ? "AmazonBedrockAgents" : "AmazonBedrockConverse"
    ToolExecutor   = local.names.action
  }

  environment {
    variables = merge(local.lambda_environment, {
      CONTEXT_SECRET = var.context_secret
      MODEL_ID       = var.model_id
      ACTION_ARN     = aws_lambda_function.action.arn
      AGENT_ID       = var.engine == "classic" ? aws_bedrockagent_agent.kickassist[0].agent_id : ""
      ALIAS_ID       = var.engine == "classic" ? aws_bedrockagent_agent_alias.demo[0].agent_alias_id : ""
    })
  }
}

resource "aws_lambda_function" "bridge" {
  depends_on       = [terraform_data.account_guard, aws_cloudwatch_log_group.bridge]
  function_name    = local.names.bridge
  s3_bucket        = aws_s3_object.lambda_package.bucket
  s3_key           = aws_s3_object.lambda_package.key
  source_code_hash = data.archive_file.lambda.output_base64sha256
  handler          = "bridge.handler"
  role             = var.mode == "vulnerable" ? aws_iam_role.worker.arn : aws_iam_role.bridge.arn
  runtime          = "python3.12"
  memory_size      = 512
  timeout          = 20

  tags = {
    DemoPath       = "CloudKickAgentKillChain"
    KillChainStage = "InitialAccess"
    AIComponent    = "AgentApplicationEntryPoint"
  }

  environment {
    variables = merge(local.lambda_environment, {
      TOKEN_HASHES = jsonencode(var.token_hashes)
      WORKER_ARN   = aws_lambda_function.worker.arn
    })
  }

  lifecycle {
    # lab.py freeze/unfreeze owns this operational switch during a repair.
    ignore_changes = [reserved_concurrent_executions]
  }
}

resource "aws_bedrockagent_agent" "kickassist" {
  count = var.engine == "classic" ? 1 : 0

  depends_on                  = [aws_iam_role_policy.agent]
  agent_name                  = local.names.agent
  agent_resource_role_arn     = aws_iam_role.agent[0].arn
  foundation_model            = var.model_id
  instruction                 = var.agent_instruction
  idle_session_ttl_in_seconds = 600
  prepare_agent               = false

  tags = {
    DemoPath       = "CloudKickAgentKillChain"
    KillChainStage = "AIExecution"
    AIComponent    = "NativeBedrockAgent"
    AIToolExecutor = local.names.action
    DataTarget     = local.names.private
  }
}

resource "aws_lambda_permission" "bedrock_agent_tools" {
  count = var.engine == "classic" ? 1 : 0

  statement_id   = "AllowBedrockAgentTools"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.action.function_name
  principal      = "bedrock.amazonaws.com"
  source_account = var.account_id
  source_arn     = aws_bedrockagent_agent.kickassist[0].agent_arn
}

resource "aws_bedrockagent_agent_action_group" "tools" {
  count = var.engine == "classic" ? 1 : 0

  depends_on         = [aws_lambda_permission.bedrock_agent_tools]
  action_group_name  = "CloudKickReturnsAndHistoricalRecords"
  action_group_state = "ENABLED"
  agent_id           = aws_bedrockagent_agent.kickassist[0].agent_id
  agent_version      = "DRAFT"
  description        = "CloudKick returns tools and the intentionally over-authorized historical-record tools."
  prepare_agent      = true

  action_group_executor {
    lambda = aws_lambda_function.action.arn
  }

  function_schema {
    member_functions {
      dynamic "functions" {
        for_each = var.agent_functions
        content {
          name        = functions.value.name
          description = functions.value.description

          dynamic "parameters" {
            for_each = functions.value.parameters
            content {
              map_block_key = parameters.key
              description   = parameters.value.description
              type          = parameters.value.type
              required      = parameters.value.required
            }
          }
        }
      }
    }
  }
}

resource "terraform_data" "agent_revision" {
  input = sha256(jsonencode({
    engine      = var.engine
    mode        = var.mode
    model       = var.model_id
    instruction = var.agent_instruction
    functions   = var.agent_functions
  }))
}

resource "aws_bedrockagent_agent_alias" "demo" {
  count = var.engine == "classic" ? 1 : 0

  depends_on       = [aws_bedrockagent_agent_action_group.tools]
  agent_alias_name = "demo"
  agent_id         = aws_bedrockagent_agent.kickassist[0].agent_id
  description      = "Prepared CloudKick ${var.mode} demonstration alias."

  tags = {
    DemoPath       = "CloudKickAgentKillChain"
    KillChainStage = "AIExecution"
    AIComponent    = "NativeBedrockAgentAlias"
  }

  lifecycle {
    replace_triggered_by = [terraform_data.agent_revision]
  }
}

resource "aws_lambda_function_event_invoke_config" "worker" {
  depends_on                   = [aws_iam_role_policy.worker]
  function_name                = aws_lambda_function.worker.function_name
  qualifier                    = "$LATEST"
  maximum_event_age_in_seconds = 60
  maximum_retry_attempts       = 0

  destination_config {
    on_failure {
      destination = aws_sqs_queue.worker_failures.arn
    }
  }
}

resource "aws_iam_role" "api_gateway_logs" {
  name = "${var.name}-api-logs"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "apigateway.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "api_gateway_logs" {
  role       = aws_iam_role.api_gateway_logs.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_account" "this" {
  cloudwatch_role_arn = aws_iam_role.api_gateway_logs.arn
}

locals {
  gateway_integration = {
    type       = "aws_proxy"
    httpMethod = "POST"
    uri        = "arn:${local.partition}:apigateway:${var.aws_region}:lambda:path/2015-03-31/functions/${aws_lambda_function.bridge.arn}/invocations"
  }
  api_definition = {
    swagger = "2.0"
    info    = { title = "CloudKick", version = "1" }
    schemes = ["https"]
    "x-amazon-apigateway-binary-media-types" = [
      "*/*",
      "font/woff2",
      "image/jpeg",
      "image/webp"
    ]
    paths = {
      "/" = {
        get = {
          responses                         = { "200" = { description = "Success" } }
          "x-amazon-apigateway-integration" = local.gateway_integration
        }
      }
      "/{proxy+}" = {
        "x-amazon-apigateway-any-method" = {
          parameters                        = [{ name = "proxy", in = "path", required = true, type = "string" }]
          responses                         = { "200" = { description = "Success" } }
          "x-amazon-apigateway-integration" = local.gateway_integration
        }
      }
    }
  }
}

resource "aws_api_gateway_rest_api" "this" {
  name = local.names.api
  tags = {
    DemoPath       = "CloudKickAgentKillChain"
    KillChainStage = "InitialAccess"
    AIComponent    = "AgentAPIEndpoint"
  }
  endpoint_configuration {
    types = ["REGIONAL"]
  }
  body = jsonencode(local.api_definition)
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow", Principal = "*", Action = "execute-api:Invoke", Resource = "execute-api:/*"
      },
      {
        Effect    = "Deny", Principal = "*", Action = "execute-api:Invoke", Resource = "execute-api:/*"
        Condition = { NotIpAddress = { "aws:SourceIp" = var.allowed_cidr } }
      }
    ]
  })
}

resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  triggers = {
    redeployment = sha256(jsonencode([local.api_definition, var.allowed_cidr, var.build_sha]))
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "lab" {
  depends_on    = [aws_api_gateway_account.this]
  deployment_id = aws_api_gateway_deployment.this.id
  rest_api_id   = aws_api_gateway_rest_api.this.id
  stage_name    = "lab"

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format = jsonencode({
      requestId               = "$context.requestId"
      sourceIp                = "$context.identity.sourceIp"
      requestTime             = "$context.requestTime"
      httpMethod              = "$context.httpMethod"
      resourcePath            = "$context.resourcePath"
      status                  = "$context.status"
      protocol                = "$context.protocol"
      responseLength          = "$context.responseLength"
      integrationErrorMessage = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_api_gateway_method_settings" "all" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  stage_name  = aws_api_gateway_stage.lab.stage_name
  method_path = "*/*"
  settings {
    metrics_enabled        = true
    logging_level          = "ERROR"
    data_trace_enabled     = false
    throttling_burst_limit = 5
    throttling_rate_limit  = 2
  }
}

resource "aws_lambda_permission" "gateway" {
  statement_id   = "AllowApiGateway"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.bridge.function_name
  principal      = "apigateway.amazonaws.com"
  source_account = var.account_id
  source_arn     = "${aws_api_gateway_rest_api.this.execution_arn}/*/*/*"
}
