# Amazon Chime Meeting Broadcast Demo

This repository contains a Docker container that, when started, will join an Amazon Chime meeting by PIN and broadcast the meeting's audio and video in high definition (1080p at 30fps). The broadcast participant (the bot) joins the meeting in the muted state. The meeting PIN must be unlocked in order for the broadcast participant to join the meeting.

## Prerequisites

You will need Docker and `make` installed on your system. As this container is running a Chrome browser instance and transcoding audio and video in real time, it is recommended to use a host system with at least 8GB RAM and 4 CPU cores, such as an m5.xlarge EC2 instance running Ubuntu Linux 18.04 LTS.
You need to give AWS credentials as environment variables to be able to use streaming transcribe SDK. If you run it on Fargate, the max duration of the credential is 6 hours. If you run it on EC2, the max duration is 1 hour.
 
## Configuration

The input for the container is a file called `container.env`. You create this file by copying the `container.env.template` to `container.env` and filling in the following variables:

* `SRC_URL`: Chime Meeting URL (without any spaces in it)
  * Example(If you want to record Chime): `https://chime.aws/<your Meeting PIN here>`
* `DST_URL`: the URL of the S3 bucket,
  * S3 example: `s3://<Bucket Name>/<Prefix>/<Key>.mp4`

### Other parameters

* `IS_RUN_ON_CONTAINER`
  * Default: True
  * set False if you run the container on EC2. (True works on Fargate)
* `BOT_NAME`
  * Default: Bot {datetime_created}
* `LOG_LEVEL`: DEBUG|INFO|WARNING|ERROR 
  *  Default: WARNING
* `API_URL`
  *  Default: https://x3ak3vyv7bgbpgoahrtwr6umyq.appsync-api.ap-northeast-1.amazonaws.com/graphql
* `MEETING_ID`: meeting ID used to write on Dynamo DB
* `LANGUAGE`
  * Default: ja-JP(Japanese)
  * [List of applicable language code](https://docs.aws.amazon.com/ja_jp/transcribe/latest/dg/transcribe-whatis.html "Amazon Transcribe とは")
* `SCREEN_WIDTH`
  * Default: 1920
* `SCREEN_HEIGHT`
  * Default: 1080
* `COLOR_DEPTH`
  * Default: 24
* `VIDEO_BITRATE`
  * Default: 4500k
* `VIDEO_FRAMERATE`
  * Default: 30
* `AUDIO_CODEC`
  * Default: aac
  * You can use flac, but flac in MP4 support is experimental.
* `AUDIO_BITRATE`
  * Default: 128k
* `AUDIO_SAMPLERATE`
  * Default: 44100
* `AUDIO_CHANNELS`
  * Default: 2
* `AUDIO_DELAYS`: You need to adjust according to the environment.
  * Default: 1800
* `THREAD_NUM`: 4 CPU cores is assumed.
  * Default: 4

## Running

To build the Docker image, run:
 
```
$ make
```
 
Once you have configured the `container.env` file, run the container:
 
```
$ make run
```
 
The container will start up and join the given Amazon Chime meeting as the `BOT_NAME` attendee and start capturing the meeting.

When your broadcast has finished, stop the stream by killing the container:

```
$ docker kill bcast
```

If you launched an EC2 instance to host the Docker container, you may also want to stop the instance to avoid incurring cost.

## Deployment

Push the Docker image to ECR and point to it from ECS.