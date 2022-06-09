#!/bin/bash

echo $REGION
echo $AWS_BRANCH
aws ssm put-parameter --name /amplify/appid --value $AWS_APP_ID --type String
aws ssm put-parameter --name /amplify/backendappid --value $AMPLIFY_BACKEND_APP_ID --type String