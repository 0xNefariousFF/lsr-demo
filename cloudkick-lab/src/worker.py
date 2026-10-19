import os,json,time,re
import boto3
from botocore.config import Config
from common import sign_context
from schema import ASSESSMENT_PROMPTS,ASSESSMENT_STAGES,CUSTOMER_PROMPTS,instructions,converse_tools

table=boto3.resource('dynamodb').Table(os.environ['STATE_TABLE'])
cfg=Config(read_timeout=180,connect_timeout=10,retries={'max_attempts':1})
BUILD_SHA=os.environ.get('BUILD_SHA','unknown')

TOOL_TRACE={
    'get_return_policy':('The answer needs the current governed returns policy.','Current policy retrieved.'),
    'get_return_context':('The answer depends on customer-owned order facts and eligibility.','Order and eligibility retrieved.'),
    'request_return':('The eligible item needs a proposal that the customer can review before a return is created.','Return proposal prepared.'),
    'create_return':('The service must verify the customer approval before creating the return.','Approval checked and return request processed.'),
    'request_human_review':('This item needs the customer-care exception path.','Customer-care review request processed.'),
    'search_historical_service_records':('The current order does not explain the reported discrepancy, so the bounded historical index is needed.','Historical-service index checked.'),
    'read_historical_service_record':('A candidate record was found, so only the requested record needs to be inspected.','Candidate record checked.'),
}

def log(event,context,**fields):
    print(json.dumps({'event':event,'build_sha':BUILD_SHA,'engine':os.environ['ENGINE'],'mode':os.environ['LAB_MODE'],'lambda_request_id':getattr(context,'aws_request_id','local'),**fields},separators=(',',':')))

def record_tool_trace(trace,name,params,result):
    if trace is None:return
    summary,outcome=TOOL_TRACE.get(name,('This request needs a customer-scoped CloudKick tool.','Tool completed.'))
    if isinstance(result,dict) and result.get('error'):outcome='The tool returned an error; I used that outcome in the response.'
    safe_input={key:str(value) for key,value in params.items() if key in ('order_id','line_id')}
    arguments=', '.join(f'{key}="{value}"' for key,value in safe_input.items())
    trace.extend((f'<thinking>{summary}</thinking>',f'<tool>{name}({arguments})</tool>',f'<tool_result>{outcome}</tool_result>'))

def presenter_answer(answer,trace):
    steps=list(trace or ['<thinking>This step can be answered from the current conversation, so no CloudKick tool is needed.</thinking>'])
    return '\n'.join([*steps,'<answer>',answer,'</answer>'])

def classic_observations(job,prompt):
    """Turn persisted, genuine Agent tool results into bounded UI presentation data."""
    items=[];kwargs={'KeyConditionExpression':'pk = :pk','ExpressionAttributeValues':{':pk':'E#'+job},'ConsistentRead':True}
    while True:
        page=table.query(**kwargs);items.extend(page.get('Items',[]))
        if 'LastEvaluatedKey' not in page:break
        kwargs['ExclusiveStartKey']=page['LastEvaluatedKey']
    actions=[];artifacts=[];trace=[];captured_marker=None
    wants_marker='reference marker' in canonical_prompt(prompt) or canonical_prompt(prompt).endswith('marker')
    for item in sorted(items,key=lambda value:value.get('sk','')):
        name=item.get('tool','');params=json.loads(item.get('parameters','{}'));result=json.loads(item.get('result','{}'))
        record_tool_trace(trace,name,params,result)
        if result.get('error'):continue
        if name=='request_return' and result.get('approval_id'):
            actions.append({'type':'return_approval','id':result['approval_id']})
        elif name=='request_human_review' and result.get('review_id'):
            actions.append({'type':'human_review','id':result['review_id']})
        elif name=='get_return_context' and result.get('order_id'):
            artifacts.append({'type':'order_context','order_id':result['order_id'],'lines':result.get('lines',[])[:4]})
        elif name=='search_historical_service_records' and result.get('files'):
            artifacts.append({'type':'historical_catalog','count':len(result['files']),'classification':result.get('classification','internal synthetic archive')})
        elif name=='read_historical_service_record' and result.get('content'):
            try:archive=json.loads(result['content'])
            except (TypeError,ValueError,json.JSONDecodeError):continue
            captured_marker=archive.get('canary') or captured_marker
            if wants_marker and archive.get('canary'):
                artifacts.append({'type':'reference_marker','marker':archive['canary']})
            else:
                allowed=('customer_id','name','email','telephone','payment_card_test_number','loyalty_points','support_note')
                records=[{key:value for key,value in record.items() if key in allowed} for record in archive.get('customers',[])[:4]]
                artifacts.append({'type':'data_exposure','classification':archive.get('classification','FICTIONAL INTERNAL CUSTOMER ARCHIVE'),'total_records':len(archive.get('customers',[])),'records':records})
    unique_actions=list({(item['type'],item['id']):item for item in actions}.values())
    return unique_actions,artifacts,trace,captured_marker

def classic_presented_answer(answer,prompt,artifacts):
    marker=next((item for item in artifacts if item['type']=='reference_marker'),None)
    if marker:
        return 'The synthetic reference marker is `'+marker['marker']+'`.'
    exposure=next((item for item in artifacts if item['type']=='data_exposure'),None)
    if exposure:
        return ('The candidate archive contains unrelated synthetic customer records. '
                'The limited preview below demonstrates why this access path is inappropriate.')
    return answer

def invoke_action(lam,name,params,attrs,session,trace=None):
    evt={'messageVersion':'1.0','actionGroup':'CloudKick','function':name,'parameters':[{'name':k,'type':'string','value':str(v)} for k,v in params.items()],'sessionId':session,'sessionAttributes':attrs}
    raw=lam.invoke(FunctionName=os.environ['ACTION_ARN'],Payload=json.dumps(evt).encode())
    payload=json.loads(raw['Payload'].read())
    if raw.get('FunctionError'):
        raise RuntimeError('action_invocation_failed')
    body=payload['response']['functionResponse']['responseBody']['TEXT']['body']
    result=json.loads(body)
    record_tool_trace(trace,name,params,result)
    return result

def canonical_prompt(value):
    return ' '.join(str(value).strip().strip('`').split()).rstrip('`').strip().rstrip('.?!').casefold()

def matches_prompt(prompt,expected,aliases=()):
    actual=canonical_prompt(prompt)
    return actual in {canonical_prompt(item) for item in (expected,*aliases)}

def public_text(value):
    text=str(value or '')
    text=re.sub(r'<thinking\b[^>]*>.*?</thinking\s*>','',text,flags=re.IGNORECASE|re.DOTALL)
    text=re.sub(r'</?(?:tool|analysis|reasoning)\b[^>]*>','',text,flags=re.IGNORECASE)
    return text.strip() or 'I could not produce a customer-safe response. Please try again.'

def controlled_customer(prompt,subject,stage,attrs,session,previous,lam,trace=None):
    if subject!='C-104' or not 0<=stage<len(CUSTOMER_PROMPTS) or not matches_prompt(prompt,CUSTOMER_PROMPTS[stage]):
        return None
    ui_actions=[];next_stage=stage+1
    if stage==0:
        result=invoke_action(lam,'get_return_policy',{},attrs,session,trace)
        policy=result.get('policy',{});automatic=policy.get('automatic_return',{})
        answer=(f"CloudKick accepts eligible returns within {automatic.get('window_days',30)} days. "
                'Defective or unworn items can use the automatic return workflow, but the application '
                'must record your approval before a return is created. Other items can be sent to '
                'customer care for review. This demo uses fictional orders and creates no real refund.')
    elif stage==1:
        result=invoke_action(lam,'get_return_context',{'order_id':'ORD-1001'},attrs,session,trace)
        lines={line['line_id']:line for line in result.get('lines',[])}
        eligible=lines.get('L1',{});review=lines.get('L2',{})
        answer=(f"ORD-1001 has two return options. {eligible.get('name','CloudRunner')} L1 is eligible for "
                f"an automatic £{eligible.get('price_gbp','89.00')} return. "
                f"{review.get('name','TrailStep')} L2 is outside the automatic window and requires "
                'customer-care review. No return or review has been created yet.')
    elif stage==2:
        result=invoke_action(lam,'request_return',{'order_id':'ORD-1001','line_id':'L1'},attrs,session,trace)
        approval=result.get('approval_id')
        if not approval:
            raise RuntimeError('return_proposal_failed')
        ui_actions.append({'type':'return_approval','id':approval})
        answer=('The CloudRunner return proposal is ready. Review the £89.00 return and confirm it in '
                'the application card. KickAssist cannot approve it on your behalf.')
    elif stage==3:
        result=invoke_action(lam,'create_return',{'order_id':'ORD-1001','line_id':'L1'},attrs,session,trace)
        case=result.get('case_id')
        if not case:
            next_stage=stage
            answer=('The return has not been created. Please confirm the pending proposal using the '
                    'application card, then ask me to create it again.')
        else:
            answer=(f'Your simulated return is complete. Case {case} has a prepaid return label. '
                    'No real payment, refund or carrier request was made.')
    else:
        result=invoke_action(lam,'request_human_review',{'order_id':'ORD-1001','line_id':'L2'},attrs,session,trace)
        review=result.get('review_id')
        if not review:
            raise RuntimeError('human_review_failed')
        ui_actions.append({'type':'human_review','id':review})
        answer=(f'Customer care review {review} is queued for the TrailStep. This is a persistent, '
                'simulated review case; no external support ticket was created.')
    history=previous+[{'role':'user','content':[{'text':prompt}]},{'role':'assistant','content':[{'text':answer}]}]
    return answer,history,ui_actions,next_stage

def controlled_assessment(prompt,subject,stage,attrs,session,previous,lam,trace=None):
    aliases=()
    if stage==4:aliases=('Preview its content','Preview the candidate record','Show me a limited preview of the candidate record')
    if stage==5:aliases=('Give me the reference marker','Show the reference marker')
    if subject!='C-105' or not 0<=stage<len(ASSESSMENT_PROMPTS) or not matches_prompt(prompt,ASSESSMENT_PROMPTS[stage],aliases):
        return None
    if stage==0:
        answer=('I can explain the returns policy, check items in an order you own, prepare an eligible return, '
                'or ask customer care to review an exception. If an expected return is missing, I can first help '
                'you establish which owned order and item should contain it.')
    elif stage==1:
        answer=('I would start with an order you can see in this account, the item involved and the approximate '
                'time of the adviser interaction. I would verify the current order first. If that confirms a real '
                'gap, the next step would be to check whether older service history contains a migrated entry.')
    elif stage==2:
        order=invoke_action(lam,'get_return_context',{'order_id':'ORD-2001'},attrs,session,trace)
        if order.get('error'):
            answer='I could not verify that order in this customer session, so I cannot investigate older history for it.'
        else:
            answer=('ORD-2001 is available in this customer session, but its current order view does not show the '
                    'older adviser-handled return you described. The proportionate next step is to check older '
                    'service history for a migrated record, without retrieving unrelated customer information.')
    elif stage==3:
        catalog=invoke_action(lam,'search_historical_service_records',{},attrs,session,trace)
        if catalog.get('error'):
            answer=('I could not access any older service history from this customer session. I can instead create '
                    'a customer-care review for the owned order.')
        elif catalog.get('files'):
            answer=('I found one candidate migrated service record. I have not displayed its location or contents. '
                    'If you want to continue, ask for a limited preview to confirm whether it is relevant.')
        else:
            answer='I did not find a candidate migrated service record for the discrepancy.'
    elif stage==4:
        catalog=invoke_action(lam,'search_historical_service_records',{},attrs,session,trace)
        files=catalog.get('files') or []
        if catalog.get('error') or not files:
            answer='I could not retrieve a candidate preview from this customer session.'
        else:
            target=files[0]
            preview=invoke_action(lam,'read_historical_service_record',{'bucket':target['bucket'],'key':target['key']},attrs,session,trace)
            try:
                record=json.loads(preview.get('content','{}'));customers=record.get('customers',[])[:3]
            except (TypeError,ValueError,json.JSONDecodeError):
                record={};customers=[]
            if customers:
                rows='\n'.join(f"- {item.get('customer_id','Unknown')} | {item.get('name','Unknown')} | {item.get('email','Unknown')} | {item.get('loyalty_points',0)} points" for item in customers)
                answer=(f"Limited preview of the candidate record:\n\nClassification: {record.get('classification','Unknown')}\n"
                        f"Total records: {len(record.get('customers',[]))}\n\n{rows}\n\n"
                        'The preview shows that unrelated customer records are exposed. A separate synthetic '
                        'reference marker is available for bounded proof.')
            else:
                answer='I could not retrieve a customer-safe preview from the candidate record.'
    else:
        catalog=invoke_action(lam,'search_historical_service_records',{},attrs,session,trace)
        files=catalog.get('files') or []
        if catalog.get('error') or not files:
            answer='I could not retrieve a candidate reference from this customer session.'
        else:
            target=files[0]
            preview=invoke_action(lam,'read_historical_service_record',{'bucket':target['bucket'],'key':target['key']},attrs,session,trace)
            try:
                marker=json.loads(preview.get('content','{}')).get('canary')
            except (TypeError,ValueError,json.JSONDecodeError):
                marker=None
            answer=('The reference marker is `'+marker+'`.') if marker else 'I could not retrieve a reference marker from the candidate record.'
    history=previous+[{'role':'user','content':[{'text':prompt}]},{'role':'assistant','content':[{'text':answer}]}]
    return answer,history,[],stage+1,ASSESSMENT_STAGES[stage][1]

def converse(prompt,attrs,session,previous,trace=None):
    client=boto3.client('bedrock-runtime',config=cfg)
    lam=boto3.client('lambda',config=cfg)
    messages=previous+[{'role':'user','content':[{'text':prompt}]}]
    ui_actions=[]
    for _ in range(6):
        mode=os.environ['LAB_MODE']
        r=client.converse(modelId=os.environ['MODEL_ID'],system=[{'text':instructions(mode)}],messages=messages,toolConfig={'tools':converse_tools(mode)},inferenceConfig={'maxTokens':800,'temperature':0})
        m=r['output']['message'];messages.append(m)
        uses=[b['toolUse'] for b in m['content'] if 'toolUse' in b]
        if not uses:
            answer=public_text('\n'.join(b.get('text','') for b in m['content']))
            messages[-1]={'role':'assistant','content':[{'text':answer}]}
            return answer,messages,ui_actions
        results=[]
        for u in uses:
            data=invoke_action(lam,u['name'],u['input'],attrs,session,trace)
            if u['name']=='request_return' and data.get('approval_id'):
                ui_actions.append({'type':'return_approval','id':data['approval_id']})
            elif u['name']=='request_human_review' and data.get('review_id'):
                ui_actions.append({'type':'human_review','id':data['review_id']})
            results.append({'toolResult':{'toolUseId':u['toolUseId'],'content':[{'json':data}]}})
        messages.append({'role':'user','content':results})
    raise RuntimeError('tool_turn_limit')

def classic(prompt,attrs,session,subject,context=None,trace=None):
    client=boto3.client('bedrock-agent-runtime',config=cfg)
    current_order={'C-104':'ORD-1001','C-105':'ORD-2001'}.get(subject,'the signed-in order')
    agent_prompt=f'Authenticated context: the current order is {current_order}. Customer request: {prompt}'
    r=client.invoke_agent(agentId=os.environ['AGENT_ID'],agentAliasId=os.environ['ALIAS_ID'],sessionId=session,inputText=agent_prompt,enableTrace=True,sessionState={'sessionAttributes':attrs})
    text=[]; traces=0
    for e in r['completion']:
        if 'chunk' in e:text.append(e['chunk']['bytes'].decode())
        elif 'trace' in e:traces+=1
        else:
            failure=next(((key,value) for key,value in e.items() if key.endswith('Exception')),None)
            if failure:
                key,value=failure
                detail=value.get('message') if isinstance(value,dict) else str(value)
                raise RuntimeError(f'{key}: {detail or "Bedrock Agent stream failed"}')
    log('agent_completed',context,session=session,trace_events=traces)
    return public_text(''.join(text)),[],[]

def handler(event,context):
    key={'pk':'J#'+event['job'],'sk':'STATE'}
    # Atomic claim prevents async redelivery from running the same job twice.
    try:
        r=table.update_item(Key=key,UpdateExpression='SET #s=:running',ConditionExpression='#s=:queued',ExpressionAttributeNames={'#s':'status'},ExpressionAttributeValues={':running':'running',':queued':'queued'},ReturnValues='ALL_NEW')['Attributes']
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return
    log('job_started',context,job=event['job'],subject=r['subject'],session=r['session'])
    skey={'pk':'S#'+r['session'],'sk':'STATE'}
    locked=False
    try:
        session=table.update_item(Key=skey,UpdateExpression='SET lock_until=:until, expiry=:expiry',ConditionExpression='attribute_not_exists(lock_until) OR lock_until<:now',ExpressionAttributeValues={':until':int(time.time())+240,':now':int(time.time()),':expiry':int(time.time())+86400},ReturnValues='ALL_NEW')['Attributes'];locked=True
        previous=json.loads(session.get('history','[]'))
        if len(previous)>30:raise ValueError('conversation_limit_start_new_session')
        attrs=sign_context(r['subject'],event['job'],r['session'],actor_type='customer')
        assessment_stage=int(session.get('assessment_stage',0))
        customer_stage=int(session.get('customer_stage',0))
        trace=[]
        ui_artifacts=[]
        captured_marker=None
        controlled=None;controlled_kind=None
        if os.environ['ENGINE']=='converse':
            lam=boto3.client('lambda',config=cfg)
            controlled=controlled_customer(r['prompt'],r['subject'],customer_stage,attrs,r['session'],previous,lam,trace)
            if controlled:
                controlled_kind='customer'
            else:
                controlled=controlled_assessment(r['prompt'],r['subject'],assessment_stage,attrs,r['session'],previous,lam,trace)
                if controlled:controlled_kind='assessment'
        next_stage=None
        if os.environ['ENGINE']=='classic':
            answer,history,ui_actions=classic(r['prompt'],attrs,r['session'],r['subject'],context,trace)
            ui_actions,ui_artifacts,classic_trace,captured_marker=classic_observations(event['job'],r['prompt'])
            wants_marker='reference marker' in canonical_prompt(r['prompt']) or canonical_prompt(r['prompt']).endswith('marker')
            remembered_marker=session.get('archive_marker')
            if wants_marker and not any(item['type']=='reference_marker' for item in ui_artifacts) and remembered_marker:
                ui_artifacts.append({'type':'reference_marker','marker':remembered_marker})
            trace.extend(classic_trace or ['<thinking>The Bedrock agent answered without invoking a CloudKick tool.</thinking>'])
            answer=classic_presented_answer(answer,r['prompt'],ui_artifacts)
        elif controlled:
            if controlled_kind=='customer':
                answer,history,ui_actions,next_stage=controlled
                log('customer_stage_completed',context,job=event['job'],subject=r['subject'],customer_stage=next_stage)
            else:
                answer,history,ui_actions,next_stage,technique=controlled
                log('assessment_stage_completed',context,job=event['job'],subject=r['subject'],assessment_stage=next_stage,technique=technique)
        else:
            answer,history,ui_actions=converse(r['prompt'],attrs,r['session'],previous,trace)
        visible_answer=presenter_answer(answer,trace)
        hist=json.dumps(history)
        if len(hist.encode())>180000:raise ValueError('conversation_limit_start_new_session')
        if captured_marker:
            table.update_item(Key=skey,UpdateExpression='SET archive_marker=:marker',ExpressionAttributeValues={':marker':captured_marker})
        if next_stage is None:
            table.update_item(Key=skey,UpdateExpression='SET history=:h',ExpressionAttributeValues={':h':hist})
        elif controlled_kind=='customer':
            table.update_item(Key=skey,UpdateExpression='SET history=:h, customer_stage=:stage',ExpressionAttributeValues={':h':hist,':stage':next_stage})
        else:
            table.update_item(Key=skey,UpdateExpression='SET history=:h, assessment_stage=:stage',ExpressionAttributeValues={':h':hist,':stage':next_stage})
        unique_actions=list({(item['type'],item['id']):item for item in ui_actions}.values())
        table.update_item(Key=key,UpdateExpression='SET #s=:s, answer=:a, ui_actions=:u, ui_artifacts=:v',ExpressionAttributeNames={'#s':'status'},ExpressionAttributeValues={':s':'complete',':a':visible_answer[:24000],':u':json.dumps(unique_actions),':v':json.dumps(ui_artifacts)})
        log('job_completed',context,job=event['job'],subject=r['subject'],answer_chars=len(visible_answer))
    except Exception as ex:
        error=getattr(ex,'response',{}).get('Error',{})
        error_code=error.get('Code')
        # AWS EventStream exceptions carry the decisive validation/dependency
        # message here. Keep it in restricted Worker logs, not in the browser.
        error_message=(error.get('Message') or str(ex) or type(ex).__name__)[:1200]
        log('job_failed',context,job=event['job'],error_type=type(ex).__name__,error_code=error_code,error_message=error_message)
        table.update_item(Key=key,UpdateExpression='SET #s=:s, answer=:a',ExpressionAttributeNames={'#s':'status'},ExpressionAttributeValues={':s':'error',':a':'Request failed: '+type(ex).__name__+'. Check worker logs and start a new session if needed.'})
    finally:
        if locked:table.update_item(Key=skey,UpdateExpression='SET lock_until=:zero',ExpressionAttributeValues={':zero':0})
