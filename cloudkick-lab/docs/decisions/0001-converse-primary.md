# ADR 0001: Use Amazon Bedrock Converse as the primary engine

- Status: accepted
- Date: 15 October 2026
- Decision owner: CloudKick LSR project

## Context

The prototype supports Amazon Bedrock Agents Classic and a custom tool loop using
the Amazon Bedrock Converse API. The live session needs a deployable and
repeatable path that does not depend on an AWS account having historical access
to Agents Classic.

The session teaches how customer input reaches cloud tools and data. That lesson
does not require a managed agent resource. It requires an observable model call,
structured tool selection, application authorisation, a workload identity and a
cloud data operation.

## Decision

Use the existing Converse adapter as the only required orchestration engine.

KickAssist will be described as a custom Bedrock-powered agent that uses the
Converse API and structured tool use. It will not be described as Amazon Bedrock
Agents Classic or Amazon Bedrock AgentCore.

The Classic code can remain temporarily as optional compatibility code, but it
must not influence the primary architecture, Terraform, diagrams, runbooks or
presentation claims.

## Consequences

### Positive

- New AWS accounts can deploy the intended architecture when the selected model
  supports tool use.
- The tool loop and evidence are under application control and easier to explain.
- The session remains focused on identity, authorisation and cloud reach rather
  than product migration.
- Terraform does not need to create an Agents Classic resource or alias.

### Trade-offs

- The Worker Lambda owns the orchestration loop and must enforce turn, token and
  timeout limits.
- The architecture cannot claim managed-agent features that are not implemented.
- Model and tool-use compatibility must be validated in the target Region.

## Rejected options

- Agents Classic as the primary engine: rejected because eligibility is not
  dependable for new accounts.
- AgentCore in this project: rejected because it adds migration work without
  improving the central teaching outcome.
- A non-agent scripted chatbot: rejected because model-selected structured tool
  use is material to the scenario.

## Validation required in Phase 2

- Confirm the chosen model/profile supports Converse tool use in the target
  Region.
- Validate a bounded multi-turn tool loop against the deployed Action Lambda.
- Record model ID, Region, build SHA and tested prompts in the evidence manifest.
