#!/bin/bash

aws ssm put-parameter --cli-input-json '{ "Name": "/amplify/app_url", "Value": "https://${AWS_BRANCH}.${AWS_APP_ID}.amplifyapp.com", "Type": "String"}'
APIURL=`aws appsync get-graphql-api --api-id `aws ssm get-parameter --name "/amplify/appsyncid"|jq -r ".Parameter.Value"`|jq -r ".graphqlApi.uris.GRAPHQL"`
aws ssm put-parameter --cli-input-json '{ "Name": "/amplify/graphqlurl", "Value: "${APIURL}", "Type":"String" }' 