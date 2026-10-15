# CloudKick / KickAssist LSR demo

CloudKick is a fictional retailer used to demonstrate how a useful AI agent can
become a cloud attack path when its tools, application authorisation and AWS
workload identity are not aligned.

The project is being developed as a 60-minute Learn and Share Remix session told
through three connected perspectives:

1. A customer uses KickAssist to understand a return policy and create a return.
2. An external customer discovers and misuses a legacy diagnostic capability.
3. A defender uses AWS evidence and Wiz context to investigate and remediate the
   same path.

The primary orchestration engine is a custom agent using the Amazon Bedrock
Converse API. It is not Amazon Bedrock Agents Classic or Amazon Bedrock
AgentCore.

## Project status

Phase 1, the authoritative scenario and architecture baseline, is complete.
Phase 2 now provides the Converse application, vulnerable and secure boundaries,
Terraform infrastructure and lifecycle utilities. Local tests and Terraform
validation pass; live AWS and Wiz acceptance remain separate release gates.

Start with:

- [`cloudkick-lab/docs/BASELINE.md`](cloudkick-lab/docs/BASELINE.md) —
  authoritative scenario, architecture, trust boundaries and demo design.
- [`cloudkick-lab/docs/IMPLEMENTATION_BACKLOG.md`](cloudkick-lab/docs/IMPLEMENTATION_BACKLOG.md)
  — ordered implementation work and acceptance gates.
- [`cloudkick-lab/docs/AWS_DEPLOYMENT_RUNBOOK.md`](cloudkick-lab/docs/AWS_DEPLOYMENT_RUNBOOK.md)
  — step-by-step sandbox deployment, validation, repair and teardown.
- [`cloudkick-lab/docs/decisions/0001-converse-primary.md`](cloudkick-lab/docs/decisions/0001-converse-primary.md)
  — engine decision.
- [`cloudkick-lab/README.md`](cloudkick-lab/README.md) — deployment and operator usage.

All identities, orders, records and return transactions are synthetic. Deploy
only into a dedicated, authorised AWS sandbox.
