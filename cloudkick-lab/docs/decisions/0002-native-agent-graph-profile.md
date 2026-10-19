# ADR 0002: Add an optional native-agent Defender graph profile

- Status: accepted
- Date: 19 October 2026
- Decision owner: CloudKick LSR project

## Context

The Converse deployment is reliable for the scripted customer demonstration, but
cloud inventory sees a Lambda invoking a hosted model rather than a managed agent.
The first Wiz investigation therefore found no agent tool/function context and the
AI identity was separated from the Lambda identity that read the private archive.

## Decision

Keep `engine=converse` as the repeatable application path and add
`engine=classic` as an optional graph-focused deployment. Terraform creates a real
Bedrock Agent, prepared alias, function-schema action group and scoped Lambda
permission. Vulnerable mode also gives Bridge, Worker and the agent-tool Lambda one
shared AI execution role with read/list access to the isolated private bucket.
Secure mode separates the Lambda identities and removes those private grants.

## Constraints

Agents Classic eligibility, Region support and model support must be verified in the
target AWS account. The profile is not AgentCore. If Classic cannot be deployed, the
Converse profile still exposes a native IAM-to-private-bucket path, but the presenter
must not claim that Wiz discovered a managed agent/action-group relationship.

A built-in Wiz Issue, sensitivity verdict and severity remain tenant outcomes. Tags
are navigation metadata, not substitute evidence. Runtime proof still comes from the
Action record and matched CloudTrail data event.
