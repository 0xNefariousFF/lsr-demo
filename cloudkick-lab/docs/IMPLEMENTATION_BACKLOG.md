# CloudKick implementation backlog

This backlog converts the Phase 1 baseline into a working AWS demonstration. Work
is ordered by dependency and presentation value. Avoid adding services unless an
acceptance criterion cannot be met without them.

## Phase 2A: repository and application baseline

Priority: P0

- [x] Remove environment configuration and editor metadata from the working tree.
- [ ] Review the existing Git history before public release; rewrite it only with explicit approval.
- [x] Make `converse` the default and primary documented engine.
- [x] Preserve the Classic adapter as non-primary compatibility code while it does not complicate tests or Terraform.
- [x] Replace smoke-test `assert` statements with explicit checks and non-zero exits.
- [x] Add a build manifest containing commit SHA, code hash, mode and model ID.
- [x] Add structured correlation IDs to Bridge, Worker and Action logs.

Acceptance:

- A fresh clone contains no account-specific configuration or editor files.
- Local tests and smoke checks cannot report success when a required check is skipped.
- Every customer job can be followed across all three functions.

## Phase 2B: legitimate customer workflow

Priority: P0

- [x] Add `get_return_policy` backed by a fixed synthetic policy object.
- [x] Retain order ownership and eligibility checks.
- [x] Retain application approval and idempotent return completion.
- [x] Add `request_human_review` and persist a review case for ineligible items.
- [x] Display proposal, return and review references clearly in the application.
- [x] Add negative tests for foreign orders, jobs, approvals and review cases.

Acceptance:

- C-104 can read the policy, inspect ORD-1001, approve L1 and create one return.
- Repeating completion returns the same case ID.
- L2 creates a review case rather than an automatic return.
- ORD-2001 does not disclose C-105 data.

## Phase 2C: deliberate vulnerable and secure modes

Priority: P0

- [x] Retain `diagnostic_catalog` and `preview_diagnostic_file` only in vulnerable mode.
- [x] Keep discovery to one prefix and preview to one exact synthetic object.
- [x] Record the S3 request ID for both ListObjectsV2 and GetObject.
- [x] Add a support-entitlement field to signed context for the secure handler check.
- [x] Ensure customer context never receives that entitlement.
- [x] Remove private S3 IAM grants in secure mode.
- [x] Test stale diagnostic calls against the secure Action handler.

Acceptance:

- Vulnerable mode can produce a successful, bounded private read.
- Secure mode rejects the tool name before S3 and IAM independently denies the read.
- Normal customer operations behave the same in both modes.

## Phase 2D: Terraform deployment

Priority: P0

- [x] Create providers, version constraints and input validation.
- [x] Package the Lambda source using the archive provider.
- [x] Create API Gateway, Lambda, DynamoDB, S3, CloudTrail, CloudWatch and IAM resources.
- [x] Add an SQS on-failure destination for Worker asynchronous invocation.
- [x] Add API access logs without request or authorisation payloads.
- [x] Add project, environment, owner, expiry and data-context tags.
- [x] Support separate vulnerable and secure names with the same module.
- [x] Add outputs required by seeding, evidence and the presenter.
- [x] Add `terraform validate`, plan and destroy instructions.

Acceptance:

- A dedicated account can deploy both stacks from documented commands.
- Terraform plan contains no account-wide data permissions.
- Destroy removes the named lab resources after evidence export.

## Phase 2E: deployment utilities

Priority: P1

- [x] Refactor the current Python utility to seed, reset, freeze, export evidence and clean data.
- [x] Read Terraform outputs rather than generated CloudFormation state.
- [x] Preserve customer tokens and the canary in a local mode-0600 state file.
- [x] Add preflight checks for account, Region, model access and caller identity.
- [x] Add a failed-job inspection and replay command.

Acceptance:

- Deploy, seed, verify, reset, freeze and destroy have documented commands.
- Utilities refuse the wrong account and broad source CIDRs.

## Phase 3: verification and CI

Priority: P1

- [ ] Unit-test Bridge, Worker, Action and evidence export.
- [ ] Contract-test the Converse tool envelope and turn limit.
- [ ] Test malformed, expired and cross-session signed context.
- [ ] Test job locking, timeout and failed-event handling.
- [ ] Run Ruff, Bandit, dependency audit, secret scan and Terraform validation in CI.
- [ ] Add browser automation for the customer and attack workflows.
- [ ] Execute live AWS acceptance tests in the authorised sandbox.

Acceptance:

- CI is green from a clean clone.
- AWS tests produce the complete evidence contract for vulnerable and secure modes.

## Phase 4: runbooks and Wiz validation

Priority: P1

- [ ] Write exact normal-customer, assessment, defender and repair runbooks.
- [ ] Record tested prompts and acceptable model variations.
- [ ] Define stop conditions and genuine recording fallbacks.
- [ ] Validate the Wiz connector, inventory scope and scan freshness.
- [ ] Record which API, Lambda, IAM and S3 relationships appear in the tenant.
- [ ] Validate telemetry ingestion separately from posture inventory.
- [ ] Test Red and Blue Agent only when available and suitable.

Acceptance:

- Another presenter can reproduce the three stories.
- Every Wiz statement is classified as observed, AWS-verified, inferred, expected or unsupported.

## Phase 5: diagrams, report and presentation source pack

Priority: P2 after the implementation is stable

- [ ] Produce four editable diagrams using official AWS Architecture Icons.
- [ ] Write the final technical report from validated evidence.
- [ ] Produce the MITRE evidence matrix.
- [ ] Create the 60-minute slide blueprint, screenshot list and speaker-note source.
- [ ] Reconcile resource names, arrows, prompts, evidence and remediation across artifacts.

Acceptance:

- Code, diagrams, report, runbooks and presentation material describe the same tested build.

## Phase 6: release rehearsal

Priority: P0 before presentation

- [ ] Deploy vulnerable and secure stacks.
- [ ] Rehearse all perspectives from clean sessions.
- [ ] Record commit, model, prompts, job IDs and evidence.
- [ ] Run the complete session to 60 minutes.
- [ ] Test fallback recordings, reset and teardown.
- [ ] Freeze a release tag and validation record.

Acceptance:

- The session can be delivered live or from clearly labelled rehearsal evidence
  without unsupported claims.
