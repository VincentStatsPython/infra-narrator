import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as path from 'path';

interface ApiStackProps extends cdk.StackProps {
  stage: string;
  poems: dynamodb.ITable;
}

/**
 * One read-only route: GET /poem returns the latest poem and a short
 * history from DynamoDB. Generation is EventBridge's job, never the
 * frontend's, so this API cannot spend model quota no matter how hard
 * anyone refreshes.
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

    this.api = new apigw.RestApi(this, 'Api', {
      restApiName: `inr-${props.stage}`,
      deployOptions: {
        stageName: props.stage,
        throttlingRateLimit: 5,
        throttlingBurstLimit: 10,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigw.Cors.ALL_ORIGINS,
        allowMethods: ['GET', 'OPTIONS'],
        allowHeaders: ['Content-Type'],
      },
    });

    this.api.root.addResource('poem').addMethod('GET', new apigw.LambdaIntegration(poemFn));

    new cdk.CfnOutput(this, 'ApiUrl', { value: this.api.url });
  }
}
