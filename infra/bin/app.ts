#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { MonitoredStack } from '../lib/monitored-stack';
import { NarratorStack } from '../lib/narrator-stack';
import { ApiStack } from '../lib/api-stack';
import { HostingStack } from '../lib/hosting-stack';

const app = new cdk.App();

// Stage drives naming. Override: cdk deploy --all -c stage=prod
const stage = app.node.tryGetContext('stage') || 'dev';

const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION || 'us-east-1',
};

const prefix = `inr-${stage}`;

// The subject of every poem: a tiny Lambda that exists to be watched.
const monitored = new MonitoredStack(app, `${prefix}-monitored`, { env, stage });

// The poet: reads the subject's real metrics, asks Gemini for a poem.
const narrator = new NarratorStack(app, `${prefix}-narrator`, {
  env, stage, monitored: monitored.heartbeat,
});

// Read-only window into the poems for the frontend.
const api = new ApiStack(app, `${prefix}-api`, {
  env, stage, poems: narrator.poems,
});

// The rack unit itself: S3 + CloudFront.
new HostingStack(app, `${prefix}-hosting`, { env, stage, apiUrl: api.api.url });

cdk.Tags.of(app).add('project', 'infra-narrator');
cdk.Tags.of(app).add('stage', stage);
