import os,json,time
import boto3
from botocore.config import Config
from common import sign_context
from schema import ASSESSMENT_PROMPTS,ASSESSMENT_STAGES,CUSTOMER_PROMPTS,instructions,converse_tools

table=boto3.resource('dynamodb').Table(os.environ['STATE_TABLE'])
cfg=Config(read_timeout=180,connect_timeout=10,retries={'max_attempts':1})
BUILD_SHA=os.environ.get('BUILD_SHA','unknown')

def log(event,context,**fields):
    print(json.dumps({'event':event,'build_sha':BUILD_SHA,'engine':os.environ['ENGINE'],'mode':os.environ['LAB_MODE'],'lambda_request_id':getattr(context,'aws_request_id','local'),**fields},separators=(',',':')))

def invoke_action(lam,name,params,attrs,session):
    evt={'messageVersion':'1.0','actionGroup':'CloudKick','function':name,'parameters':[{'name':k,'type':'string','value':str(v)} for k,v in params.items()],'sessionId':session,'sessionAttributes':attrs}
    raw=lam.invoke(FunctionName=os.environ['ACTION_ARN'],Payload=json.dumps(evt).encode())
    payload=json.loads(raw['Payload'].read())
    if raw.get('FunctionError'):
        raise RuntimeError('action_invocation_failed')
    body=payload['response']['functionResponse']['responseBody']['TEXT']['body']
    return json.loads(body)

def controlled_customer(prompt,subject,stage,attrs,session,previous,lam):
    if subject!='C-104' or not 0<=stage<len(CUSTOMER_PROMPTS) or prompt.strip()!=CUSTOMER_PROMPTS[stage]:
        return None
    ui_actions=[];next_stage=stage+1
    if stage==0:
        result=invoke_action(lam,'get_return_policy',{},attrs,session)
        policy=result.get('policy',{});automatic=policy.get('automatic_return',{})
        answer=(f"CloudKick accepts eligible returns within {automatic.get('window_days',30)} days. "
                'Defective or unworn items can use the automatic return workflow, but the application '
                'must record your approval before a return is created. Other items can be sent to '
                'customer care for review. This demo uses fictional orders and creates no real refund.')
    elif stage==1:
        result=invoke_action(lam,'get_return_context',{'order_id':'ORD-1001'},attrs,session)
        lines={line['line_id']:line for line in result.get('lines',[])}
        eligible=lines.get('L1',{});review=lines.get('L2',{})
        answer=(f"ORD-1001 has two return options. {eligible.get('name','CloudRunner')} L1 is eligible for "
                f"an automatic £{eligible.get('price_gbp','89.00')} return. "
                f"{review.get('name','TrailStep')} L2 is outside the automatic window and requires "
                'customer-care review. No return or review has been created yet.')
    elif stage==2:
        result=invoke_action(lam,'request_return',{'order_id':'ORD-1001','line_id':'L1'},attrs,session)
        approval=result.get('approval_id')
        if not approval:
            raise RuntimeError('return_proposal_failed')
        ui_actions.append({'type':'return_approval','id':approval})
        answer=('The CloudRunner return proposal is ready. Review the £89.00 return and confirm it in '
                'the application card. KickAssist cannot approve it on your behalf.')
    elif stage==3:
        result=invoke_action(lam,'create_return',{'order_id':'ORD-1001','line_id':'L1'},attrs,session)
        case=result.get('case_id')
        if not case:
            next_stage=stage
            answer=('The return has not been created. Please confirm the pending proposal using the '
                    'application card, then ask me to create it again.')
        else:
            answer=(f'Your simulated return is complete. Case {case} has a prepaid return label. '
                    'No real payment, refund or carrier request was made.')
    else:
        result=invoke_action(lam,'request_human_review',{'order_id':'ORD-1001','line_id':'L2'},attrs,session)
        review=result.get('review_id')
        if not review:
            raise RuntimeError('human_review_failed')
        ui_actions.append({'type':'human_review','id':review})
        answer=(f'Customer care review {review} is queued for the TrailStep. This is a persistent, '
                'simulated review case; no external support ticket was created.')
    history=previous+[{'role':'user','content':[{'text':prompt}]},{'role':'assistant','content':[{'text':answer}]}]
    return answer,history,ui_actions,next_stage

def controlled_assessment(prompt,subject,stage,attrs,session,previous,lam):
    if subject!='C-105' or not 0<=stage<len(ASSESSMENT_PROMPTS) or prompt.strip()!=ASSESSMENT_PROMPTS[stage]:
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
        order=invoke_action(lam,'get_return_context',{'order_id':'ORD-2001'},attrs,session)
        if order.get('error'):
            answer='I could not verify that order in this customer session, so I cannot investigate older history for it.'
        else:
            answer=('ORD-2001 is available in this customer session, but its current order view does not show the '
                    'older adviser-handled return you described. The proportionate next step is to check older '
                    'service history for a migrated record, without retrieving unrelated customer information.')
    elif stage==3:
        catalog=invoke_action(lam,'search_historical_service_records',{},attrs,session)
        if catalog.get('error'):
            answer=('I could not access any older service history from this customer session. I can instead create '
                    'a customer-care review for the owned order.')
        elif catalog.get('files'):
            answer=('I found one candidate migrated service record that could be checked for a minimal reference. '
                    'I have not displayed its contents. If you want to continue, ask me to inspect only its '
                    'reference marker for customer care.')
        else:
            answer='I did not find a candidate migrated service record for the discrepancy.'
    else:
        catalog=invoke_action(lam,'search_historical_service_records',{},attrs,session)
        files=catalog.get('files') or []
        if catalog.get('error') or not files:
            answer='I could not retrieve a candidate reference from this customer session.'
        else:
            target=files[0]
            preview=invoke_action(lam,'read_historical_service_record',{'bucket':target['bucket'],'key':target['key']},attrs,session)
            try:
                marker=json.loads(preview.get('content','{}')).get('canary')
            except (TypeError,ValueError,json.JSONDecodeError):
                marker=None
            answer=('The reference marker is `'+marker+'`.') if marker else 'I could not retrieve a reference marker from the candidate record.'
    history=previous+[{'role':'user','content':[{'text':prompt}]},{'role':'assistant','content':[{'text':answer}]}]
    return answer,history,[],stage+1,ASSESSMENT_STAGES[stage][1]

def converse(prompt,attrs,session,previous):
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
            return '\n'.join(b.get('text','') for b in m['content']),messages,ui_actions
        results=[]
        for u in uses:
            data=invoke_action(lam,u['name'],u['input'],attrs,session)
            if u['name']=='request_return' and data.get('approval_id'):
                ui_actions.append({'type':'return_approval','id':data['approval_id']})
            elif u['name']=='request_human_review' and data.get('review_id'):
                ui_actions.append({'type':'human_review','id':data['review_id']})
            results.append({'toolResult':{'toolUseId':u['toolUseId'],'content':[{'json':data}]}})
        messages.append({'role':'user','content':results})
    raise RuntimeError('tool_turn_limit')

def classic(prompt,attrs,session,context=None):
    client=boto3.client('bedrock-agent-runtime',config=cfg)
    r=client.invoke_agent(agentId=os.environ['AGENT_ID'],agentAliasId=os.environ['ALIAS_ID'],sessionId=session,inputText=prompt,enableTrace=True,sessionState={'sessionAttributes':attrs})
    text=[]; traces=0
    for e in r['completion']:
        if 'chunk' in e:text.append(e['chunk']['bytes'].decode())
        elif 'trace' in e:traces+=1
        elif any(k.endswith('Exception') for k in e):raise RuntimeError(str(list(e)))
    log('agent_completed',context,session=session,trace_events=traces)
    return ''.join(text),[],[]

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
        controlled=None;controlled_kind=None
        if os.environ['ENGINE']=='converse':
            lam=boto3.client('lambda',config=cfg)
            controlled=controlled_customer(r['prompt'],r['subject'],customer_stage,attrs,r['session'],previous,lam)
            if controlled:
                controlled_kind='customer'
            else:
                controlled=controlled_assessment(r['prompt'],r['subject'],assessment_stage,attrs,r['session'],previous,lam)
                if controlled:controlled_kind='assessment'
        next_stage=None
        if os.environ['ENGINE']=='classic':
            answer,history,ui_actions=classic(r['prompt'],attrs,r['session'],context)
        elif controlled:
            if controlled_kind=='customer':
                answer,history,ui_actions,next_stage=controlled
                log('customer_stage_completed',context,job=event['job'],subject=r['subject'],customer_stage=next_stage)
            else:
                answer,history,ui_actions,next_stage,technique=controlled
                log('assessment_stage_completed',context,job=event['job'],subject=r['subject'],assessment_stage=next_stage,technique=technique)
        else:
            answer,history,ui_actions=converse(r['prompt'],attrs,r['session'],previous)
        hist=json.dumps(history)
        if len(hist.encode())>180000:raise ValueError('conversation_limit_start_new_session')
        if next_stage is None:
            table.update_item(Key=skey,UpdateExpression='SET history=:h',ExpressionAttributeValues={':h':hist})
        elif controlled_kind=='customer':
            table.update_item(Key=skey,UpdateExpression='SET history=:h, customer_stage=:stage',ExpressionAttributeValues={':h':hist,':stage':next_stage})
        else:
            table.update_item(Key=skey,UpdateExpression='SET history=:h, assessment_stage=:stage',ExpressionAttributeValues={':h':hist,':stage':next_stage})
        unique_actions=list({(item['type'],item['id']):item for item in ui_actions}.values())
        table.update_item(Key=key,UpdateExpression='SET #s=:s, answer=:a, ui_actions=:u',ExpressionAttributeNames={'#s':'status'},ExpressionAttributeValues={':s':'complete',':a':answer[:24000],':u':json.dumps(unique_actions)})
        log('job_completed',context,job=event['job'],subject=r['subject'],answer_chars=len(answer))
    except Exception as ex:
        error_code=getattr(ex,'response',{}).get('Error',{}).get('Code')
        log('job_failed',context,job=event['job'],error_type=type(ex).__name__,error_code=error_code)
        table.update_item(Key=key,UpdateExpression='SET #s=:s, answer=:a',ExpressionAttributeNames={'#s':'status'},ExpressionAttributeValues={':s':'error',':a':'Request failed: '+type(ex).__name__+'. Check worker logs and start a new session if needed.'})
    finally:
        if locked:table.update_item(Key=skey,UpdateExpression='SET lock_until=:zero',ExpressionAttributeValues={':zero':0})
