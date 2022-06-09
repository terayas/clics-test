#!/bin/bash

aws ssm put-parameter --cli-input-json '{ "Name": "/amplify/appurl", "Value": "https://${USER_BRANCH}.${AWS_APP_ID}.amplifyapp.com", "Type": "String"}'