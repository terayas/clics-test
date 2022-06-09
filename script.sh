#!/bin/bash


aws configure set cli_follow_urlparam false
# Put Amplify App URL to SSM Parameter at app_url
aws ssm put-parameter --name "/amplify/app_url" --value "https://${AWS_BRANCH}.${AWS_APP_ID}.amplifyapp.com" --type "String" --overwrite

API_ID=`aws ssm get-parameter --name "/amplify/appsyncid"|jq -r ".Parameter.Value"`

# Get Graphql API URI 
APIURL=`aws appsync get-graphql-api --api-id ${API_ID}|jq -r ".graphqlApi.uris.GRAPHQL"`


# Put Graphql API URI to SSM Param at /amplify/graphqlurl
aws ssm put-parameter --name "/amplify/graphql_api" --value "${APIURL}" --type "String" --overwrite

# Put DynamoDB Table to SSM Param at /amplify/tablename
aws ssm put-parameter --name "/amplify/tablename" --value `aws appsync get-data-source --api-id ${API_ID} --name TodoTable|jq -r ".dataSource.dynamodbConfig.tableName"` --type "String" --overwrite

# Put Account
aws ssm put-parameter --name "/amplify/account" --value `aws sts get-caller-identity|jq -r ".Account"` --Type "String" --overwrite