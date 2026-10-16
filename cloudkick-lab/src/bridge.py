import os,json,time,uuid,hashlib,re,base64
from decimal import Decimal
from pathlib import Path
import boto3
from boto3.dynamodb.conditions import Key

table=boto3.resource('dynamodb').Table(os.environ['STATE_TABLE'])
lam=boto3.client('lambda')
BUILD_SHA=os.environ.get('BUILD_SHA','unknown')
ROOT=Path(__file__).resolve().parent
ASSETS={
    '/assets/cloudkick-returns-hero.jpg':('image/jpeg','cloudkick-returns-hero.jpg'),
    '/assets/cloudrunner-grey.webp':('image/webp','cloudrunner-grey.webp'),
    '/assets/trailstep-black.webp':('image/webp','trailstep-black.webp'),
    '/assets/inter-400.woff2':('font/woff2','inter-400.woff2'),
    '/assets/inter-600.woff2':('font/woff2','inter-600.woff2'),
    '/assets/inter-700.woff2':('font/woff2','inter-700.woff2'),
}

def log(event,context,**fields):
    print(json.dumps({'event':event,'build_sha':BUILD_SHA,'lambda_request_id':getattr(context,'aws_request_id','local'),**fields},separators=(',',':')))

def reply(status,obj,html=False):
    return {'statusCode':status,'headers':{'Content-Type':'text/html; charset=utf-8' if html else 'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Permissions-Policy':'camera=(), microphone=(), geolocation=()','Content-Security-Policy':"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"},'body':obj if html else json.dumps(obj,default=lambda v:int(v) if isinstance(v,Decimal) else str(v))}

def asset_reply(path):
    content_type,name=ASSETS[path]
    return {'statusCode':200,'headers':{'Content-Type':content_type,'Cache-Control':'public, max-age=3600, immutable','X-Content-Type-Options':'nosniff'},'isBase64Encoded':True,'body':base64.b64encode((ROOT/'assets'/name).read_bytes()).decode()}

def handler(event,context):
    path=event.get('path','/');method=event.get('httpMethod','GET')
    if path=='/' and method=='GET':return reply(200,(ROOT/'index.html').read_text(),True)
    if method=='GET' and path in ASSETS:return asset_reply(path)
    if int(os.environ['LAB_EXPIRES'])<time.time():return reply(403,{'error':'lab_expired'})
    headers={k.lower():v for k,v in (event.get('headers') or {}).items()}
    raw=headers.get('authorization','')
    token=raw[7:] if raw.startswith('Bearer ') else ''
    subject=json.loads(os.environ['TOKEN_HASHES']).get(hashlib.sha256(token.encode()).hexdigest())
    if not subject:return reply(401,{'error':'invalid_session'})
    try:
        raw_body=event.get('body') or '{}'
        if event.get('isBase64Encoded'):
            try:
                raw_body=base64.b64decode(raw_body,validate=True).decode('utf-8')
            except Exception as ex:
                raise ValueError('invalid_base64_body') from ex
        body=json.loads(raw_body)
        if not isinstance(body,dict):raise ValueError('invalid_body')
        if method=='GET' and path=='/me':return reply(200,{'customer':subject,'engine':os.environ['ENGINE'],'mode':os.environ['LAB_MODE'],'build_sha':BUILD_SHA})
        if method=='POST' and path=='/chat':
            prompt=body.get('message','');session=body.get('session','')
            if not isinstance(prompt,str) or not 1<=len(prompt)<=2000 or not re.fullmatch(r'[a-zA-Z0-9-]{8,64}',session):raise ValueError('invalid_message_or_session')
            sid=hashlib.sha256((subject+':'+session).encode()).hexdigest()
            job=uuid.uuid4().hex
            table.put_item(Item={'pk':'J#'+job,'sk':'STATE','subject':subject,'session':sid,'prompt':prompt,'status':'queued','expiry':int(time.time())+86400})
            lam.invoke(FunctionName=os.environ['WORKER_ARN'],InvocationType='Event',Payload=json.dumps({'job':job}).encode())
            log('job_queued',context,job=job,subject=subject,session=sid)
            return reply(202,{'job':job})
        if method=='GET' and path.startswith('/jobs/'):
            job=path.rsplit('/',1)[1]
            item=table.get_item(Key={'pk':'J#'+job,'sk':'STATE'},ConsistentRead=True).get('Item',{})
            if item.get('subject')!=subject:return reply(404,{'error':'not_found'})
            # Expose only the worker's curated activity summaries, never raw tool output or model trace.
            result={k:item[k] for k in ('status','answer') if k in item}
            if item.get('ui_actions'):
                result['actions']=json.loads(item['ui_actions'])
            if item.get('activity'):
                result['activity']=json.loads(item['activity'])
            return reply(200,result)
        if method=='GET' and path.startswith('/approvals/'):
            aid=path.rsplit('/',1)[1]
            item=table.get_item(Key={'pk':'A#'+aid,'sk':'STATE'},ConsistentRead=True).get('Item',{})
            if item.get('subject')!=subject:return reply(404,{'error':'not_found'})
            return reply(200,{k:item[k] for k in ('approval_id','status','order_id','line_id','item_name','amount_gbp','reason','size','colour','return_method','expiry') if k in item})
        if method=='GET' and path.startswith('/reviews/'):
            rid=path.rsplit('/',1)[1]
            if not re.fullmatch(r'REV-[A-F0-9]{12}',rid):raise ValueError('invalid_review')
            item=table.get_item(Key={'pk':'R#'+rid,'sk':'STATE'},ConsistentRead=True).get('Item',{})
            if item.get('subject')!=subject:return reply(404,{'error':'not_found'})
            return reply(200,{k:item[k] for k in ('review_id','status','order_id','line_id','item_name','reason','expiry')})
        if method=='POST' and path=='/approve':
            aid=body.get('approval_id','')
            if not re.fullmatch(r'[a-f0-9]{24}',aid):raise ValueError('invalid_approval')
            table.update_item(Key={'pk':'A#'+aid,'sk':'STATE'},UpdateExpression='SET #s=:yes',ConditionExpression='subject=:subject AND #s=:pending AND expiry>:now',ExpressionAttributeNames={'#s':'status'},ExpressionAttributeValues={':subject':subject,':pending':'pending',':yes':'approved',':now':int(time.time())})
            log('return_approved',context,approval_id=aid,subject=subject)
            return reply(200,{'status':'approved'})
        return reply(404,{'error':'not_found'})
    except (ValueError,TypeError):return reply(400,{'error':'invalid_request'})
    except table.meta.client.exceptions.ConditionalCheckFailedException:return reply(409,{'error':'proposal_missing_expired_or_not_pending'})
