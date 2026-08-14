import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
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

  constructor(scope: Construct, id: string, props: NarratorStackProps) {
    super(scope, id, props);

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
        MODEL_FALLBACKS: 'gemini-3.5-flash-lite',
        WINDOW_MIN: '5',
      },
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
