import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as path from 'path';

interface MonitoredStackProps extends cdk.StackProps {
  stage: string;
}

/**
 * The monitored heartbeat - a near-empty Lambda deployed purely to emit real
 * CloudWatch metrics. The load generator invokes it at varying rates and
 * modes (ok / slow / error) to create genuine quiet, busy, degraded and
 * erroring conditions for the narrator to read.
 *
 * Reserved concurrency is deliberately tiny (5) so a real burst from the
 * load generator can produce real Throttles, not just Invocations.
 */
export class MonitoredStack extends cdk.Stack {
  public readonly heartbeat: lambda.Function;

  constructor(scope: Construct, id: string, props: MonitoredStackProps) {
    super(scope, id, props);

    this.heartbeat = new lambda.Function(this, 'Heartbeat', {
      functionName: `inr-monitored-${props.stage}`,
      description: 'Exists to be watched. The subject of every poem.',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'monitored.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambdas')),
      timeout: cdk.Duration.seconds(10),
      memorySize: 128,
      reservedConcurrentExecutions: 5,
    });

    new cdk.CfnOutput(this, 'HeartbeatFunctionName', { value: this.heartbeat.functionName });
  }
}
