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
 * No reserved concurrency: this account's total Lambda concurrency is capped
 * at 10, so reservations are impossible (they would drop the unreserved pool
 * below its minimum of 10). The cap works in our favour anyway - a real burst
 * of slow concurrent invocations hits the account ceiling and produces real
 * Throttles without any reservation.
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
    });

    new cdk.CfnOutput(this, 'HeartbeatFunctionName', { value: this.heartbeat.functionName });
  }
}
