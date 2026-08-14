#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { MonitoredStack } from '../lib/monitored-stack';

const app = new cdk.App();

// Stage drives naming. Override: cdk deploy --all -c stage=prod
const stage = app.node.tryGetContext('stage') || 'dev';

const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION || 'us-east-1',
};

const prefix = `inr-${stage}`;

// The subject of every poem: a tiny Lambda that exists to be watched.
new MonitoredStack(app, `${prefix}-monitored`, { env, stage });

cdk.Tags.of(app).add('project', 'infra-narrator');
cdk.Tags.of(app).add('stage', stage);
