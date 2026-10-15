"""Generate a CloudFormation template. Concrete AWS identifiers come from deployment."""
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'src'))
from schema import classic_functions,INSTRUCTIONS

def template(c,artifact_bucket,artifact_key):
    name=c['name'];region=c['region'];account=c['account'];mode=c['mode'];classic=c['engine']=='classic'
    arn=lambda service,resource:f'arn:aws:{service}:{region}:{account}:{resource}'
    ref=lambda x:{'Ref':x}
    att=lambda x,k='Arn':{'Fn::GetAtt':[x,k]}
    roles={x:f'{name}-{x.lower()}' for x in ['Bridge','Worker','Action','Agent']}
    funcs={x:f'{name}-{x.lower()}' for x in ['Bridge','Worker','Action']}
    buckets={x:f'{name}-{account}-{region}-{x.lower()}' for x in ['Orders','Private','Audit']}
    state=name+'-state';tablearn=arn('dynamodb','table/'+state)
    tags=[{'Key':'Project','Value':'CloudKick'},{'Key':'Environment','Value':'isolated-lab'},{'Key':'Owner','Value':c['owner']},{'Key':'ExpiresAt','Value':str(c['expires'])}]
    def stmt(actions,res,**kw):return dict(Effect='Allow',Action=actions,Resource=res,**kw)
    def role(kind,statements,service='lambda.amazonaws.com'):
        trust={'Effect':'Allow','Principal':{'Service':service},'Action':'sts:AssumeRole'}
        if service=='bedrock.amazonaws.com':trust['Condition']={'StringEquals':{'aws:SourceAccount':account},'ArnLike':{'aws:SourceArn':arn('bedrock','agent/*')}}
        return {'Type':'AWS::IAM::Role','Properties':{'RoleName':roles[kind],'AssumeRolePolicyDocument':{'Version':'2012-10-17','Statement':[trust]},'Policies':[{'PolicyName':'CloudKickScope','PolicyDocument':{'Version':'2012-10-17','Statement':statements}}],'Tags':tags}}
    def logs(kind):return stmt(['logs:CreateLogStream','logs:PutLogEvents'],arn('logs','log-group:/aws/lambda/'+funcs[kind]+':*'))
    def db(actions):return stmt(actions,tablearn)
    r={}
    for kind,bucket in buckets.items():
        r[kind+'Bucket']={'Type':'AWS::S3::Bucket','DeletionPolicy':'Retain','UpdateReplacePolicy':'Retain','Properties':{'BucketName':bucket,'PublicAccessBlockConfiguration':{x:True for x in ('BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets')},'OwnershipControls':{'Rules':[{'ObjectOwnership':'BucketOwnerEnforced'}]},'BucketEncryption':{'ServerSideEncryptionConfiguration':[{'ServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]},'Tags':tags}}
        statements=[{'Effect':'Deny','Principal':'*','Action':'s3:*','Resource':[f'arn:aws:s3:::{bucket}',f'arn:aws:s3:::{bucket}/*'],'Condition':{'Bool':{'aws:SecureTransport':'false'}}}]
        if kind=='Audit':
            for act,res in [('s3:GetBucketAcl',f'arn:aws:s3:::{bucket}'),('s3:PutObject',f'arn:aws:s3:::{bucket}/AWSLogs/{account}/*')]:
                cond={'StringEquals':{'aws:SourceArn':arn('cloudtrail','trail/'+name)}}
                if act=='s3:PutObject':cond['StringEquals']['s3:x-amz-acl']='bucket-owner-full-control'
                statements.append(dict(Effect='Allow',Principal={'Service':'cloudtrail.amazonaws.com'},Action=act,Resource=res,Condition=cond))
        r[kind+'Policy']={'Type':'AWS::S3::BucketPolicy','Properties':{'Bucket':ref(kind+'Bucket'),'PolicyDocument':{'Version':'2012-10-17','Statement':statements}}}
    r['State']={'Type':'AWS::DynamoDB::Table','Properties':{'TableName':state,'BillingMode':'PAY_PER_REQUEST','AttributeDefinitions':[{'AttributeName':'pk','AttributeType':'S'},{'AttributeName':'sk','AttributeType':'S'}],'KeySchema':[{'AttributeName':'pk','KeyType':'HASH'},{'AttributeName':'sk','KeyType':'RANGE'}],'TimeToLiveSpecification':{'AttributeName':'expiry','Enabled':True},'SSESpecification':{'SSEEnabled':True},'Tags':tags}}
    r['Trail']={'Type':'AWS::CloudTrail::Trail','DependsOn':['AuditPolicy'],'Properties':{'TrailName':name,'S3BucketName':ref('AuditBucket'),'IsLogging':True,'IsMultiRegionTrail':False,'IncludeGlobalServiceEvents':False,'EnableLogFileValidation':True,'AdvancedEventSelectors':[{'Name':'CloudKickObjectEvidence','FieldSelectors':[{'Field':'eventCategory','Equals':['Data']},{'Field':'resources.type','Equals':['AWS::S3::Object']},{'Field':'resources.ARN','StartsWith':[f'arn:aws:s3:::{buckets[x]}/' for x in ('Orders','Private')]}]}],'Tags':tags}}
    actionstm=[logs('Action'),db(['dynamodb:GetItem','dynamodb:PutItem','dynamodb:UpdateItem']),stmt('s3:GetObject',[f'arn:aws:s3:::{buckets["Orders"]}/orders/*',f'arn:aws:s3:::{buckets["Orders"]}/policies/returns.json'])]
    if mode=='vulnerable':
        actionstm += [stmt('s3:GetObject',f'arn:aws:s3:::{buckets["Private"]}/cloudkick/customer-records.json'),stmt('s3:ListBucket',f'arn:aws:s3:::{buckets["Private"]}',Condition={'StringLike':{'s3:prefix':'cloudkick/*'}})]
    r['ActionRole']=role('Action',actionstm)
    modelstmt=stmt(['bedrock:InvokeModel','bedrock:InvokeModelWithResponseStream'],c['model_arns'])
    workerstm=[logs('Worker'),db(['dynamodb:GetItem','dynamodb:PutItem','dynamodb:UpdateItem'])]
    if classic:
        r['AgentRole']=role('Agent',[modelstmt],'bedrock.amazonaws.com')
        r['Agent']={'Type':'AWS::Bedrock::Agent','Properties':{'AgentName':name,'AgentResourceRoleArn':att('AgentRole'),'FoundationModel':c['model_id'],'Instruction':INSTRUCTIONS,'AutoPrepare':True,'IdleSessionTTLInSeconds':600,'Tags':{x['Key']:x['Value'] for x in tags},'ActionGroups':[{'ActionGroupName':'CloudKick','ActionGroupState':'ENABLED','ActionGroupExecutor':{'Lambda':att('ActionFunction')},'FunctionSchema':{'Functions':classic_functions(mode)}}]}}
        # A new logical alias resource per configuration builds a fresh agent version.
        revision=hashlib.sha256(json.dumps([mode,c['model_id'],artifact_key,INSTRUCTIONS,classic_functions(mode)]).encode()).hexdigest()[:10]
        alias='AgentAlias'+revision
        r[alias]={'Type':'AWS::Bedrock::AgentAlias','Properties':{'AgentId':ref('Agent'),'AgentAliasName':'demo-'+revision,'Description':'CloudKick '+mode+' '+revision}}
        r['BedrockInvokePermission']={'Type':'AWS::Lambda::Permission','Properties':{'FunctionName':ref('ActionFunction'),'Action':'lambda:InvokeFunction','Principal':'bedrock.amazonaws.com','SourceAccount':account,'SourceArn':att('Agent','AgentArn')}}
        workerstm.append(stmt('bedrock:InvokeAgent',att(alias,'AgentAliasArn')))
    else:
        workerstm += [modelstmt,stmt('lambda:InvokeFunction',arn('lambda','function:'+funcs['Action']))]
    r['WorkerRole']=role('Worker',workerstm)
    r['BridgeRole']=role('Bridge',[logs('Bridge'),db(['dynamodb:GetItem','dynamodb:PutItem','dynamodb:UpdateItem']),stmt('lambda:InvokeFunction',arn('lambda','function:'+funcs['Worker']))])
    base={'STATE_TABLE':state,'LAB_MODE':mode,'ENGINE':c['engine'],'LAB_EXPIRES':str(c['expires']),'BUILD_SHA':c.get('build_sha','unrecorded')}
    for kind in ['Action','Worker','Bridge']:
        env=dict(base)
        if kind in ('Action','Worker'):env['CONTEXT_SECRET']=ref('ContextSecret')
        if kind=='Action':env.update(ORDERS_BUCKET=buckets['Orders'],POLICY_BUCKET=buckets['Orders'],PRIVATE_BUCKET=buckets['Private'])
        if kind=='Worker':
            env.update(MODEL_ID=c['model_id'],ACTION_ARN=arn('lambda','function:'+funcs['Action']))
            if classic:env.update(AGENT_ID=ref('Agent'),ALIAS_ID=att(alias,'AgentAliasId'))
        if kind=='Bridge':env.update(TOKEN_HASHES=json.dumps(c['token_hashes']),WORKER_ARN=arn('lambda','function:'+funcs['Worker']))
        r[kind+'Log']={'Type':'AWS::Logs::LogGroup','Properties':{'LogGroupName':'/aws/lambda/'+funcs[kind],'RetentionInDays':3,'Tags':tags}}
        r[kind+'Function']={'Type':'AWS::Lambda::Function','DependsOn':[kind+'Log'],'Properties':{'FunctionName':funcs[kind],'Runtime':'python3.12','Handler':kind.lower()+'.handler','MemorySize':512,'Timeout':240 if kind=='Worker' else 20,'Role':att(kind+'Role'),'Code':{'S3Bucket':artifact_bucket,'S3Key':artifact_key},'Environment':{'Variables':env},'Tags':tags}}
    r['WorkerAsync']={'Type':'AWS::Lambda::EventInvokeConfig','Properties':{'FunctionName':ref('WorkerFunction'),'Qualifier':'$LATEST','MaximumRetryAttempts':0,'MaximumEventAgeInSeconds':60}}
    integration={'type':'aws_proxy','httpMethod':'POST','uri':f'arn:aws:apigateway:{region}:lambda:path/2015-03-31/functions/{arn("lambda","function:"+funcs["Bridge"])}/invocations'}
    paths={'/':{'get':{'responses':{'200':{'description':'Success'}},'x-amazon-apigateway-integration':integration}},'/{proxy+}':{'x-amazon-apigateway-any-method':{'parameters':[{'name':'proxy','in':'path','required':True,'type':'string'}],'responses':{'200':{'description':'Success'}},'x-amazon-apigateway-integration':integration}}}
    policy={'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':'*','Action':'execute-api:Invoke','Resource':'execute-api:/*'},{'Effect':'Deny','Principal':'*','Action':'execute-api:Invoke','Resource':'execute-api:/*','Condition':{'NotIpAddress':{'aws:SourceIp':c['allowed_cidr']}}}]}
    r['Api']={'Type':'AWS::ApiGateway::RestApi','Properties':{'Name':name,'EndpointConfiguration':{'Types':['REGIONAL']},'Policy':policy,'Body':{'swagger':'2.0','info':{'title':'CloudKick','version':'1'},'paths':paths},'Tags':tags}}
    deploy='ApiDeployment'+hashlib.sha256(json.dumps([paths,policy]).encode()).hexdigest()[:10]
    r[deploy]={'Type':'AWS::ApiGateway::Deployment','Properties':{'RestApiId':ref('Api')}}
    r['Stage']={'Type':'AWS::ApiGateway::Stage','Properties':{'StageName':'lab','RestApiId':ref('Api'),'DeploymentId':ref(deploy),'MethodSettings':[{'ResourcePath':'/*','HttpMethod':'*','ThrottlingBurstLimit':5,'ThrottlingRateLimit':2}],'Tags':tags}}
    r['GatewayPermission']={'Type':'AWS::Lambda::Permission','Properties':{'FunctionName':ref('BridgeFunction'),'Action':'lambda:InvokeFunction','Principal':'apigateway.amazonaws.com','SourceArn':{'Fn::Sub':f'arn:aws:execute-api:{region}:{account}:${{Api}}/*/*/*'},'SourceAccount':account}}
    outs={x+'Bucket':{'Value':b} for x,b in buckets.items()}
    outs.update(ApiUrl={'Value':{'Fn::Sub':f'https://${{Api}}.execute-api.{region}.amazonaws.com/lab/'}},StateTable={'Value':state},ActionRole={'Value':roles['Action']},ActionFunction={'Value':funcs['Action']})
    if classic:outs.update(AgentId={'Value':ref('Agent')},AliasId={'Value':att(alias,'AgentAliasId')})
    return {'AWSTemplateFormatVersion':'2010-09-09','Description':'CloudKick fictional isolated teaching lab','Parameters':{'ContextSecret':{'Type':'String','NoEcho':True,'MinLength':32}},'Resources':r,'Outputs':outs}
