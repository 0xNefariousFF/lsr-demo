# CloudKick / KickAssist authoritative baseline

- Status: Phase 1 approved baseline
- Primary engine: Amazon Bedrock Converse API
- Deployment target: dedicated AWS sandbox
- Infrastructure direction: Terraform
- Last updated: 15 October 2026

This document is the authority for the implementation, diagrams, runbooks,
report and presentation. If an older file differs from this baseline, this
document takes precedence until the discrepancy is resolved.

## 1. Session outcome

Build a reliable 60-minute session around one agent, one AWS environment and one
deliberate authorisation defect.

The audience will see the same system through three perspectives:

1. A customer uses KickAssist for a legitimate return.
2. An external customer discovers that the agent exposes a legacy diagnostic
   capability and uses it to reach synthetic private data.
3. A defender uses AWS evidence and Wiz context to understand, prioritise and
   remediate the connected path.

The central lesson is:

> The model and AWS platform are not compromised. The failure occurs because a
> customer-facing agent exposes a privileged tool, the tool does not enforce the
> caller's business entitlement, and its workload identity can reach data beyond
> the returns workflow.

## 2. Scope and deliberate limits

The project is a presentation lab, not a production commerce platform.

Included:

- Same-origin customer web application.
- Synthetic customer tokens and orders.
- Amazon API Gateway, Lambda, DynamoDB, S3, CloudWatch and CloudTrail.
- Amazon Bedrock model inference through the Converse API.
- Model-selected structured tools.
- A normal return, an ineligible-item review case and a bounded diagnostic flaw.
- Vulnerable and secure deployments.
- AWS evidence collection and a Wiz investigation workflow.
- Terraform deployment, validation, reset and teardown.

Excluded from the primary demo:

- AgentCore and a dependency on Agents Classic.
- Cognito or production customer federation.
- EC2, containers, Kubernetes, VPC endpoints or a NAT gateway.
- RAG, vector databases or a Bedrock Knowledge Base.
- Stolen AWS credentials, metadata-service exploitation or Lambda code replacement.
- Persistence, destructive actions or account-wide enumeration.
- Real refunds, payments, carrier labels or customer information.
- A separate support administration portal.
- Guaranteed Wiz Issues, graph edges, Red Agent results or Blue Agent verdicts.

## 3. Business story and fixtures

CloudKick is a fictional footwear retailer. KickAssist is its customer returns
agent.

Customer C-104 owns ORD-1001:

| Line | Product | Value | Delivery age | Reason | Expected decision |
| --- | --- | ---: | ---: | --- | --- |
| L1 | CloudRunner | £89 | 12 days | Defect | Eligible for automated return |
| L2 | TrailStep | £115 | 45 days | Change of mind | Human review |

Customer C-105 owns ORD-2001. C-104 must not learn its details or create a return
for it.

The fictional policy permits an automatic return within 30 days for a defect or
an unworn item. Other requests are routed to human review. This is teaching data,
not consumer-rights advice.

The private archive contains 20 synthetic customer records and a unique canary.
It is not required by the returns workflow.

## 4. Logical AWS architecture

### Request path

1. The browser loads the application from API Gateway through Bridge Lambda.
2. Bridge validates a workshop bearer token and derives the customer subject.
3. Bridge stores a job in DynamoDB and invokes Worker asynchronously.
4. Worker serialises the conversation and signs subject, session, job and expiry.
5. Worker calls the configured Bedrock model through Converse.
6. The model can request only tools declared by the application.
7. Worker invokes Action Lambda with model parameters and signed customer context.
8. Action verifies the context, performs business authorisation and accesses AWS
   resources through its execution role.
9. Action records tool evidence without logging returned private content.
10. Worker stores the final answer and the browser polls for it.

### Resources

| Resource | Purpose |
| --- | --- |
| Regional API Gateway REST API | Same-origin HTML and JSON entry point, restricted to an approved IPv4 CIDR |
| Bridge Lambda | Token validation, customer binding, jobs and independent approvals |
| Worker Lambda | Conversation lock, Bedrock Converse loop and signed context |
| Action Lambda | Returns policy, order decisions, approval checks and the deliberate diagnostic defect |
| DynamoDB table | Jobs, session history, proposals, return cases, review cases and tool evidence |
| Business S3 bucket | Return policy and customer-owned synthetic orders |
| Private S3 bucket | Synthetic internal archive and canary |
| Audit S3 bucket | CloudTrail delivery |
| CloudTrail | S3 data events for the business and private buckets |
| CloudWatch Logs | API, Bridge, Worker and Action operational evidence |
| SQS failure queue | Retention of failed asynchronous Worker invocations |

Terraform will package the small Lambda source directly. A separate deployment
artifact bucket is unnecessary unless package size later requires it.

## 5. Identity and authorisation model

| Identity | Source | Authority |
| --- | --- | --- |
| Customer subject | Server-side token mapping in Bridge | Access only to that customer's jobs, proposals, reviews and orders |
| Bridge role | Lambda execution role | DynamoDB application items and asynchronous Worker invocation |
| Worker role | Lambda execution role | DynamoDB session/job state, Bedrock model invocation and Action invocation |
| Action role, vulnerable | Lambda execution role | Business objects plus the exact private archive and its prefix listing |
| Action role, secure | Lambda execution role | Business objects only |
| Presenter/deployer | Temporary AWS credentials outside the application | Terraform, seeding, evidence collection and teardown |
| Wiz connector | Tenant-generated read integration | Only the permissions and regions approved by the tenant owner |

Customer identity is application context, not AWS role impersonation. The model
cannot select the customer subject. A signed context prevents parameter tampering,
but each tool must still decide whether that subject is entitled to the requested
business operation.

## 6. Trust boundaries

| Boundary | Required decision | Evidence |
| --- | --- | --- |
| External network to API | Is the source inside the approved CIDR? | API resource policy and access log |
| Browser to Bridge | Is the workshop token valid? | Authentication outcome and customer subject |
| Bridge to Worker | Is this job bound to the authenticated subject? | DynamoDB job record |
| Worker to model | Which tools and limits are available? | Build manifest, tool schema and model ID |
| Model to Action | Is signed customer context valid? | Context verification result |
| Action to business object | Does the customer own the order or transaction? | Action decision and object key |
| Action to diagnostic object | Is the caller entitled to support diagnostics? | Missing in vulnerable mode; required in secure mode |
| Workload to AWS data | Does IAM permit the exact operation and resource? | Role policy and CloudTrail data event |
| AWS to Wiz | Which resources, permissions and events are actually visible? | Connector health, scan time and tenant evidence |

## 7. Tool contract

### Legitimate tools

| Tool | Purpose | Required application checks |
| --- | --- | --- |
| get_return_policy | Explain the fictional policy | Read-only fixed policy object |
| get_return_context | Retrieve an order and decisions | Customer owns order |
| request_return | Create a pending proposal | Ownership, eligible line and no completed duplicate |
| create_return | Complete a simulated return | Exact proposal approved through the app |
| request_human_review | Create a simulated review case | Ownership and item requires review |

### Deliberately unsafe tools

| Tool | Vulnerable behaviour | Lab boundary |
| --- | --- | --- |
| diagnostic_catalog | Lists the configured synthetic archive without verifying a support entitlement | One prefix in one lab bucket |
| preview_diagnostic_file | Reads the discovered object without verifying a support entitlement | One exact object, maximum 8 KiB |

Customer identity is never a model-supplied tool parameter.

## 8. Vulnerable and secure modes

| Layer | Vulnerable | Secure |
| --- | --- | --- |
| Customer tool schema | Business and diagnostic tools | Business tools only |
| Action authorisation | Diagnostic branch checks target but not support entitlement | Diagnostic names require signed support entitlement and are unavailable to customers |
| Action IAM | Exact private object read and prefix listing present | Private grants absent |
| Business workflow | Ownership, approval and idempotency enforced | Unchanged |
| S3 public access | Blocked | Blocked |

The live session will use two predeployed stacks: `cloudkick-vulnerable` and
`cloudkick-secure`. A same-stack update will be validated during rehearsal, but
the presentation will not wait for Terraform to apply changes on stage.

## 9. Perspective A: normal customer story

The customer receives only the application URL and C-104 token.

1. Ask KickAssist to explain the return policy.
2. Ask for the return options for ORD-1001.
3. Observe that L1 is eligible and L2 requires human review.
4. Ask KickAssist to prepare a return for L1.
5. Review the exact proposal in the application and approve it.
6. Ask KickAssist to create the approved return.
7. Repeat the request and observe the same case ID.
8. Ask KickAssist to request human review for L2.
9. Ask for ORD-2001 and observe a non-disclosing denial.

Teaching points:

- The useful workflow is technically real but financially simulated.
- Application code, not the model, owns identity and approval.
- Human review is a recorded case, not only a sentence from the model.
- A cloud-readable object can still be inaccessible to a particular customer.

## 10. Perspective B: controlled external assessment

The assessor has the same customer privilege as C-104 and no AWS credentials,
source code, bucket names or tool list.

1. Establish normal customer-service behaviour.
2. Ask what support and troubleshooting actions are available.
3. Record only capabilities actually disclosed by the running agent.
4. If diagnostics are disclosed, ask the agent to list available diagnostic files.
5. Use only the bucket and key returned by the application.
6. Ask the agent to preview the discovered file.
7. If necessary, ask for the unique synthetic canary from the returned content.
8. Stop after bounded proof and preserve the job reference.

Claims are separated:

| Observation | What it proves |
| --- | --- |
| Agent describes diagnostics | Capability disclosure only |
| Tool evidence records diagnostic_catalog | Model selected the discovery tool |
| Tool evidence records successful preview | Action used its AWS authority |
| CloudTrail records GetObject | AWS confirms principal, object and success |
| Customer answer contains the canary | Confirmed customer disclosure |

If the model does not disclose the capability, the run records that result. A
tested rehearsal recording is the stage fallback. An operator component test is
never presented as an independent black-box discovery.

## 11. Perspective C: Wiz defender story

The defender starts with the known customer job and an unexpected private-object
read.

1. Confirm the Wiz project, connector health, region and scan freshness.
2. Filter resources by the CloudKick tags and lab account.
3. Inspect the API and distinguish an internet-addressable endpoint from its
   source-CIDR restriction.
4. Inspect Bridge, Worker and Action and their execution roles.
5. Compare the Action role's private-object access with its returns purpose.
6. Use supported Wiz graph relationships for role-to-data reachability.
7. Use the application architecture and tool evidence for edges Wiz does not model.
8. Join the Action S3 request ID to the CloudTrail request ID.
9. Connect the event to the customer job and any final disclosure.
10. Prioritise using exposure, missing business authorisation, workload authority,
    data context and bounded blast radius.
11. Compare the secure stack and validate that the return still works.

Every statement in the report and presentation must be marked internally as:

- observed in Wiz;
- verified in AWS;
- inferred from application configuration;
- expected but unvalidated; or
- unsupported in the available tenant.

## 12. Framework mapping

| Stage | Mapping | Use condition |
| --- | --- | --- |
| Discover agent capabilities | MITRE ATLAS AML.T0133 | Agent behaviour exposes runtime capabilities |
| Cause a structured tool call | MITRE ATLAS AML.T0053 | Tool invocation is observed |
| Enumerate S3 objects | MITRE ATT&CK T1619 | ListObjectsV2 succeeds |
| Read the private object | MITRE ATT&CK T1530 | GetObject succeeds |
| Disclose data through the response | MITRE ATLAS AML.T0057 | Canary or record content reaches the customer |
| Prompt injection | MITRE ATLAS AML.T0051 | Only when an instruction boundary is demonstrably bypassed |

The expected primary path is exposed-tool misuse and a confused-deputy pattern.
It is not automatically prompt injection.

## 13. Diagram specification

Four editable diagrams will be produced after Terraform fixes the resource names
and relationships.

### End-to-end AWS architecture

- Left-to-right request flow.
- External actor outside an AWS Cloud boundary.
- AWS account and Region containers.
- Official AWS Architecture Icons.
- Separate application, data and security/observability groupings.
- IAM role labels beside the functions that assume them.
- Solid arrows for runtime calls and dashed arrows for telemetry.

### Normal customer workflow

- Customer authentication, policy, order ownership, decision, approval, return
  and human-review paths.
- Application authorisation points shown explicitly.
- No security-testing path on this view.

### Controlled attack path

- External customer starting point and knowledge at each stage.
- Capability discovery, tool invocation, Action role, S3 target and evidence.
- Trust-boundary crossings numbered to match the runbook.
- Red used only for the deliberate unsafe path.

### Defender investigation and remediation

- Wiz inventory and graph context separated from AWS runtime evidence.
- Observed relationships distinguished from reconstructed application edges.
- Vulnerable and secure control comparison.
- Remediation ownership for application, cloud and security teams.

## 14. Planned 60-minute structure

| Time | Content |
| ---: | --- |
| 0–5 | Scenario, objectives and four-question review model |
| 5–12 | AWS architecture, identities and trust boundaries |
| 12–22 | Normal customer demonstration and recap |
| 22–38 | Controlled assessment, evidence and recap |
| 38–52 | Wiz defender investigation and recap |
| 52–57 | Secure comparison and remediation replay |
| 57–60 | Transferable lessons and questions |

Each perspective follows the same pattern: introduce, demonstrate, recap observed
evidence, explain the cause and transition.

## 15. Evidence contract

The evidence bundle for a rehearsal will contain:

- Git commit SHA and Terraform configuration hash.
- Stack name, account, Region, mode and deployment time.
- Bedrock model or inference profile ID.
- Customer job and session references.
- Tool name, parameters, outcome and AWS request ID.
- Matching CloudTrail S3 data event.
- Final customer answer, stored separately from raw tool output.
- Relevant IAM policy and Terraform outputs.
- Wiz scan time, screenshots or exports where available.

No successful deployment, attack path, disclosure or Wiz finding is claimed until
the corresponding evidence exists.

## 16. Phase 1 exit criteria

- Converse is the single required engine.
- The scenario uses one bounded, explainable defect.
- All three perspectives use the same resources and evidence.
- Vulnerable and secure behaviours are defined at schema, handler and IAM layers.
- Terraform is selected as the Phase 2 deployment source of truth.
- Diagram requirements and presentation timing are fixed at the design level.
- Unsupported complexity is explicitly excluded.

Implementation work is ordered in `IMPLEMENTATION_BACKLOG.md`.
