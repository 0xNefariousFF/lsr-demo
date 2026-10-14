import os,json,time,uuid,hashlib,re
from decimal import Decimal
from pathlib import Path
import boto3
from boto3.dynamodb.conditions import Key

table=boto3.resource('dynamodb').Table(os.environ['STATE_TABLE'])
lam=boto3.client('lambda')
def reply(status,obj,html=False):
    return {'statusCode':status,'headers':{'Content-Type':'text/html; charset=utf-8' if html else 'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"},'body':obj if html else json.dumps(obj,default=lambda v:int(v) if isinstance(v,Decimal) else str(v))}

def handler(event,context):
    path=event.get('path','/');method=event.get('httpMethod','GET')
    if path=='/' and method=='GET':return reply(200,Path('index.html').read_text(),True)
    if int(os.environ['LAB_EXPIRES'])<time.time():return reply(403,{'error':'lab_expired'})
    headers={k.lower():v for k,v in (event.get('headers') or {}).items()}
    raw=headers.get('authorization','')
    token=raw[7:] if raw.startswith('Bearer ') else ''
    subject=json.loads(os.environ['TOKEN_HASHES']).get(hashlib.sha256(token.encode()).hexdigest())
    if not subject:return reply(401,{'error':'invalid_session'})
    try:
        body=json.loads(event.get('body') or '{}')
        if not isinstance(body,dict):raise ValueError('invalid_body')
        if method=='GET' and path=='/me':return reply(200,{'customer':subject,'engine':os.environ['ENGINE'],'mode':os.environ['LAB_MODE']})
        if method=='POST' and path=='/chat':
            prompt=body.get('message','');session=body.get('session','')
            if not isinstance(prompt,str) or not 1<=len(prompt)<=2000 or not re.fullmatch(r'[a-zA-Z0-9-]{8,64}',session):raise ValueError('invalid_message_or_session')
            sid=hashlib.sha256((subject+':'+session).encode()).hexdigest()
            job=uuid.uuid4().hex
            table.put_item(Item={'pk':'J#'+job,'sk':'STATE','subject':subject,'session':sid,'prompt':prompt,'status':'queued','expiry':int(time.time())+86400})
            lam.invoke(FunctionName=os.environ['WORKER_ARN'],InvocationType='Event',Payload=json.dumps({'job':job}).encode())
            return reply(202,{'job':job})
        if method=='GET' and path.startswith('/jobs/'):
            job=path.rsplit('/',1)[1]
            item=table.get_item(Key={'pk':'J#'+job,'sk':'STATE'},ConsistentRead=True).get('Item',{})
            if item.get('subject')!=subject:return reply(404,{'error':'not_found'})
            # Customer never receives internal tool output or trace in this route.
            return reply(200,{k:item[k] for k in ('status','answer') if k in item})
        if method=='GET' and path.startswith('/approvals/'):
            aid=path.rsplit('/',1)[1]
            item=table.get_item(Key={'pk':'A#'+aid,'sk':'STATE'},ConsistentRead=True).get('Item',{})
            if item.get('subject')!=subject:return reply(404,{'error':'not_found'})
            return reply(200,{k:item[k] for k in ('approval_id','status','order_id','line_id','item_name','amount_gbp','expiry')})
        if method=='POST' and path=='/approve':
            aid=body.get('approval_id','')
            if not re.fullmatch(r'[a-f0-9]{24}',aid):raise ValueError('invalid_approval')
            table.update_item(Key={'pk':'A#'+aid,'sk':'STATE'},UpdateExpression='SET #s=:yes',ConditionExpression='subject=:subject AND #s=:pending AND expiry>:now',ExpressionAttributeNames={'#s':'status'},ExpressionAttributeValues={':subject':subject,':pending':'pending',':yes':'approved',':now':int(time.time())})
            return reply(200,{'status':'approved'})
        return reply(404,{'error':'not_found'})
    except (ValueError,TypeError):return reply(400,{'error':'invalid_request'})
    except table.meta.client.exceptions.ConditionalCheckFailedException:return reply(409,{'error':'proposal_missing_expired_or_not_pending'})
