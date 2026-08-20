import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as path from 'path';

interface ApiStackProps extends cdk.StackProps {
  stage: string;
  poems: dynamodb.ITable;
}

/**
 * GET /poem is read-only: the latest poem and a short history from
 * DynamoDB. Generation from live metrics is EventBridge's job, never the
 * frontend's, so refreshing the page cannot spend model quota.
 *
 * POST /simulate is the one route that can, so it is fenced: a fixed set of
 * three states, a per-state cooldown in the Lambda, and API Gateway
 * throttling above that. Its poems are stored under their own key and never
 * reach the real history.
 */
export class ApiStack extends cdk.Stack {
  public readonly api: apigw.RestApi;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const poemFn = new lambda.Function(this, 'GetPoemFn', {
      functionName: `inr-get-poem-${props.stage}`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'get_poem.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambdas'), {
        exclude: ['__pycache__'],
      }),
      timeout: cdk.Duration.seconds(10),
      memorySize: 256,
      environment: { TABLE_NAME: props.poems.tableName },
    });
    props.poems.grantReadData(poemFn);

    const simulateFn = new lambda.Function(this, 'SimulateFn', {
      functionName: `inr-simulate-${props.stage}`,
      description: 'Replays a recorded condition and asks for a poem from inside it.',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'simulate.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambdas'), {
        exclude: ['__pycache__'],
      }),
      timeout: cdk.Duration.seconds(29), // API Gateway's own ceiling
      memorySize: 256,
      environment: {
        TABLE_NAME: props.poems.tableName,
        GEMINI_SECRET_NAME: 'infra-narrator/gemini',
        MODEL_ID: 'gemini-3.5-flash-lite',
        MODEL_FALLBACKS: 'gemini-flash-latest,gemini-3.5-flash',
        // Behind API Gateway's 29s wall, so the fast model leads here even
        // though the scheduled narrator can afford to lead with the primary.
        GEMINI_TIMEOUT_S: '12',
        GEMINI_FALLBACK_TIMEOUT_S: '8',
        SIM_COOLDOWN_S: '45',
      },
    });
    props.poems.grantReadWriteData(simulateFn);
    simulateFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [
        `arn:aws:secretsmanager:${this.region}:${this.account}:secret:infra-narrator/gemini*`,
      ],
    }));

    this.api = new apigw.RestApi(this, 'Api', {
      restApiName: `inr-${props.stage}`,
      deployOptions: {
        stageName: props.stage,
        throttlingRateLimit: 5,
        throttlingBurstLimit: 10,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigw.Cors.ALL_ORIGINS,
        allowMethods: ['GET', 'POST', 'OPTIONS'],
        allowHeaders: ['Content-Type'],
      },
    });

    this.api.root.addResource('poem').addMethod('GET', new apigw.LambdaIntegration(poemFn));
    this.api.root.addResource('simulate').addMethod('POST', new apigw.LambdaIntegration(simulateFn));

    new cdk.CfnOutput(this, 'ApiUrl', { value: this.api.url });
  }
}
