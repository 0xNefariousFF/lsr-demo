#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:?Set AWS_REGION before running this check.}"
: "${MODEL_ID:?Set MODEL_ID before running this check.}"

command -v aws >/dev/null || { printf 'ERROR: aws is required.\n' >&2; exit 1; }
command -v jq >/dev/null || { printf 'ERROR: jq is required.\n' >&2; exit 1; }

attempts="${1:-3}"
if ! [[ "$attempts" =~ ^[1-9][0-9]*$ ]]; then
  printf 'ERROR: attempts must be a positive integer.\n' >&2
  exit 1
fi

initial_messages='[{"role":"user","content":[{"text":"Use get_return_policy now. Do not answer from memory. After the tool result, reply with RETURN_POLICY_OK and the return window in days."}]}]'
tool_config='{"tools":[{"toolSpec":{"name":"get_return_policy","description":"Retrieve the fictional CloudKick return policy.","inputSchema":{"json":{"type":"object","properties":{},"additionalProperties":false}}}}]}'
inference_config='{"maxTokens":200,"temperature":0}'

for ((attempt = 1; attempt <= attempts; attempt++)); do
  first_response=$(aws bedrock-runtime converse \
    --region "$AWS_REGION" \
    --model-id "$MODEL_ID" \
    --messages "$initial_messages" \
    --tool-config "$tool_config" \
    --inference-config "$inference_config" \
    --output json)

  jq -e '
    [.output.message.content[] | select(.toolUse != null) | .toolUse] as $uses
    | .stopReason == "tool_use"
      and ($uses | length) == 1
      and $uses[0].name == "get_return_policy"
      and $uses[0].input == {}
  ' >/dev/null <<<"$first_response" || {
    printf 'FAIL %d/%d: expected one get_return_policy tool request.\n' "$attempt" "$attempts" >&2
    jq '{stopReason, content: .output.message.content}' <<<"$first_response" >&2
    exit 1
  }

  assistant_message=$(jq -c '.output.message' <<<"$first_response")
  tool_use_id=$(jq -r '.output.message.content[] | select(.toolUse != null) | .toolUse.toolUseId' <<<"$first_response")
  followup_messages=$(jq -cn \
    --argjson initial "$initial_messages" \
    --argjson assistant "$assistant_message" \
    --arg tool_use_id "$tool_use_id" \
    '$initial + [$assistant, {"role":"user","content":[{"toolResult":{"toolUseId":$tool_use_id,"status":"success","content":[{"json":{"status":"RETURN_POLICY_OK","return_window_days":30}}]}}]}]')

  final_response=$(aws bedrock-runtime converse \
    --region "$AWS_REGION" \
    --model-id "$MODEL_ID" \
    --messages "$followup_messages" \
    --tool-config "$tool_config" \
    --inference-config "$inference_config" \
    --output json)

  jq -e '
    ([.output.message.content[] | select(.toolUse != null)] | length) == 0
    and ([.output.message.content[] | .text? // empty] | join(" ") | test("RETURN_POLICY_OK"))
    and ([.output.message.content[] | .text? // empty] | join(" ") | test("30"))
  ' >/dev/null <<<"$final_response" || {
    printf 'FAIL %d/%d: the model did not consume the tool result correctly.\n' "$attempt" "$attempts" >&2
    jq '{stopReason, content: .output.message.content}' <<<"$final_response" >&2
    exit 1
  }

  printf 'PASS %d/%d: Converse tool request and tool-result round trip succeeded.\n' "$attempt" "$attempts"
done

printf 'MODEL PREFLIGHT PASSED: %s in %s\n' "$MODEL_ID" "$AWS_REGION"
