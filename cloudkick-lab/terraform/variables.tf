variable "name" {
  description = "Unique lab deployment name."
  type        = string

  validation {
    condition     = can(regex("^cloudkick-[a-z0-9-]{1,16}$", var.name))
    error_message = "name must start with cloudkick- and contain at most 16 additional lowercase letters, digits, or hyphens."
  }
}

variable "account_id" {
  description = "Explicit isolated AWS lab account ID."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be a 12-digit AWS account ID."
  }
}

variable "aws_region" {
  description = "AWS region in which to create the lab."
  type        = string
}

variable "owner" {
  description = "Owner tag for all lab resources."
  type        = string
}

variable "allowed_cidr" {
  description = "Presenter IPv4 /32 or another narrow IPv4 range no broader than /24."
  type        = string

  validation {
    condition     = can(cidrhost(var.allowed_cidr, 0)) && length(regexall("^[0-9.]+/(2[4-9]|3[0-2])$", var.allowed_cidr)) == 1
    error_message = "allowed_cidr must be an IPv4 CIDR with a /24 through /32 prefix."
  }
}

variable "mode" {
  description = "Intentionally vulnerable or remediated comparison stack."
  type        = string

  validation {
    condition     = contains(["vulnerable", "secure"], var.mode)
    error_message = "mode must be vulnerable or secure."
  }
}

variable "model_id" {
  description = "Bedrock foundation model ID or inference profile ID used by Converse."
  type        = string
}

variable "model_invoke_arns" {
  description = "Exact model and inference profile ARNs required by the selected model ID."
  type        = list(string)
}

variable "expires_epoch" {
  description = "Unix epoch after which application requests are rejected."
  type        = number
}

variable "context_secret" {
  description = "HMAC secret used for server-signed customer/actor context."
  type        = string
  sensitive   = true
}

variable "token_hashes" {
  description = "SHA-256 token hash to synthetic customer ID map."
  type        = map(string)
  sensitive   = true
}

variable "build_sha" {
  description = "Immutable application build identifier included in logs and UI metadata."
  type        = string
}
