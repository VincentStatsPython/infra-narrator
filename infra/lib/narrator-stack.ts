import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as path from 'path';

interface NarratorStackProps extends cdk.StackProps {
  stage: string;
  monitored: lambda.IFunction;
}

/**
 * The narrator - reads the heartbeat's real CloudWatch metrics, derives the
 * metaphor descriptors, calls Gemini (key in Secrets Manager) and returns
 * the poem. Storage and the EventBridge schedule arrive in the next phase.
 */
export class NarratorStack extends cdk.Stack {
  public readonly narrator: lambda.Function;
  public readonly poems: dynamodb.Table;

  constructor(scope: Construct, id: string, props: NarratorStackProps) {
    super(scope, id, props);

    // Latest poem lives at pk=LATEST; history rows are pk=POEM, sk=timestamp
    // and expire after a week so the table cannot quietly accumulate.
    this.poems = new dynamodb.Table(this, 'Poems', {
      tableName: `inr-poems-${props.stage}`,
      partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'sk', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'expires_at',
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    this.narrator = new lambda.Function(this, 'Narrator', {
      functionName: `inr-narrator-${props.stage}`,
      description: 'Reads real metrics, writes the machine a poem.',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'narrator.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambdas'), {
        exclude: ['__pycache__'],
      }),
      timeout: cdk.Duration.seconds(60),
      memorySize: 256,
      environment: {
        MONITORED_FUNCTION: props.monitored.functionName,
        GEMINI_SECRET_NAME: 'infra-narrator/gemini',
        MODEL_ID: 'gemini-flash-latest',
        MODEL_FALLBACKS: 'gemini-3.5-flash,gemini-3.5-flash-lite',
        WINDOW_MIN: '5',
        TABLE_NAME: this.poems.tableName,
        // no API Gateway in this path, so the primary model can breathe;
        // observed: gemini-flash-latest times out at the inherited 18s
        GEMINI_TIMEOUT_S: '30',
        GEMINI_FALLBACK_TIMEOUT_S: '12',
      },
    });
    this.poems.grantWriteData(this.narrator);

    // The whole point: the machine reports on itself, unattended.
    new events.Rule(this, 'NarrateSchedule', {
      ruleName: `inr-narrate-${props.stage}`,
      schedule: events.Schedule.rate(cdk.Duration.minutes(15)),
      targets: [new targets.LambdaFunction(this.narrator)],
    });

    // GetMetricData takes no resource-level scoping; the reads stay honest.
    this.narrator.addToRolePolicy(new iam.PolicyStatement({
      actions: ['cloudwatch:GetMetricData'],
      resources: ['*'],
    }));
    this.narrator.addToRolePolicy(new iam.PolicyStatement({
      actions: ['lambda:GetFunctionConfiguration'],
      resources: [props.monitored.functionArn],
    }));
    this.narrator.addToRolePolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [
        `arn:aws:secretsmanager:${this.region}:${this.account}:secret:infra-narrator/gemini*`,
      ],
    }));

    new cdk.CfnOutput(this, 'NarratorFunctionName', { value: this.narrator.functionName });
  }
}
