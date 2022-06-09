#!/bin/bash

echo $REGION
echo $AWS_BRANCH
echo $ACCOUNT
aws ssm put-parameter --name /amplify/backendappid --value $AMPLIFY_BACKEND_APP_ID --type String