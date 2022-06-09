#!/bin/bash

cd clics-bot-container

AWS_ACCOUNT=`aws ssm get-parameter --name "/amplify/account"|jq -r ".Parameter.Value"`
ECR_REPOSITORY_NAME=`aws ssm get-parameter --name "/amplify/ecr_name"|jq -r ".Parameter.Value"`
aws ecr get-login-password --region ${AWS_Region} | docker login --username AWS --password-stdin ${AWS_ACCOUNT}.dkr.ecr.${AWS_Region}.amazonaws.com
docker build -t bot .
docker tag bot ${AWS_ACCOUNT}.dkr.ecr.${AWS_Region}.amazonaws.com/${ECR_REPOSITORY_NAME}:latest
docker push ${AWS_ACCOUNT}.dkr.ecr.${AWS_Region}.amazonaws.com/${ECR_REPOSITORY_NAME}:latest