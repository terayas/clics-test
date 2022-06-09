#!/bin/bash

cd clics-bot-container

AWS_ACCOUNT=`aws ssm get-parameter --name "/amplify/account"|jq -r ".Parameter.Value"`
aws ecr get-login-password --region ${AWS_Region} | docker login --username AWS --password-stdin ${AWS_ACCOUNT}.dkr.ecr.${AWS_Region}.amazonaws.com