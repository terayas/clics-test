import sys
import os
import re
import json
import urllib.request
from time import sleep
from collections import defaultdict
from logging import getLogger, StreamHandler, basicConfig, Formatter
from subprocess import TimeoutExpired
from selenium import webdriver
from selenium.webdriver.support.expected_conditions import visibility_of_element_located
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.relative_locator import with_tag_name
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import WebDriverException
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from pyvirtualdisplay import Display
import chromedriver_binary
import ffmpeg
import uuid
import boto3
import signal
import datetime
# modules for Transcribe streaming SDK
import asyncio
import sounddevice
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent
# modules for AppSync
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport
from requests_aws4auth import AWS4Auth

###### logger configuration ######
log_level = os.getenv('LOG_LEVEL', "WARNING")
def get_logger(log_level="WARNING"):
    log_format = "%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s"
    basicConfig(format=log_format, level=log_level)  # 細かく呼び出しモジュールのログも見る 
    logger = getLogger(__name__)
    handler = StreamHandler()
    handler.setLevel(log_level)
    handler.setFormatter(Formatter(log_format))
    logger.setLevel(log_level)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
logger = get_logger(log_level)
#################################

###### get environment variables ######
# note that SRC_URL and DST_URL must be specified
# vars for media
screen_width = os.getenv('SCREEN_WIDTH', 1920)
screen_height = os.getenv('SCREEN_HEIGHT', 1080)
screen_resolution = f'{screen_width}x{screen_height}'
color_depth = os.getenv('COLOR_DEPTH', 24)
video_bitrate = os.getenv('VIDEO_BITRATE', '4500k')
#video_minrate = os.getenv('VIDEO_MINRATE', '3000k')
#video_maxrate = os.getenv('VIDEO_MAXRATE', '6000k')
#video_bufsize = os.getenv('VIDEO_BUFSIZE', '12000k')
video_framerate = os.getenv('VIDEO_FRAMERATE', 30)
filter_framerate = round(video_framerate / 1.001, 2)
video_gop = video_framerate * 2
audio_codec = os.getenv('AUDIO_CODEC', 'aac')
audio_bitrate = os.getenv('AUDIO_BITRATE', '128k')
audio_samplerate = os.getenv('AUDIO_SAMPLERATE', 44100)
audio_channels = os.getenv('AUDIO_CHANNELS', 2)
audio_delays = os.getenv('AUDIO_DELAYS', '0') #'2000')
thread_num = os.getenv('THREAD_NUM', 4)
# vars for Transcribe and AppSync
API_URL = os.getenv('API_URL','https://x3ak3vyv7bgbpgoahrtwr6umyq.appsync-api.ap-northeast-1.amazonaws.com/graphql')
meeting_id = os.getenv('MEETING_ID', "meeting_id_not_presented")
language_code = os.getenv('LANGUAGE',"ja-JP")
SNSTopicArn = os.getenv('SNS_TOPIC_ARN')
lambda_arn = os.getenv('UPDATE_MEETING_TABLE_LAMBDA_ARN')

src_url = os.getenv('SRC_URL')
if not src_url:
    logger.error("source URL must be specified! (e.g. SRC_URL=https://chime.aws/1111111111)")
    sys.exit(1)

dst_url = os.getenv('DST_URL')
if not dst_url:
    logger.error("destination URL must be specified! (e.g. DST_URL=s3://{BUCKET_NAME}/path to file/{FILE_NAME}.mp4)")
    sys.exit(1)

dst_type = dst_url.split('://')[0]
if dst_type == 's3':
    s3_bucket = dst_url.split('/')[2]
    s3_key = '/'.join(dst_url.split('/')[3:])
    output_format = dst_url.split('.')[-1]
    tmp_file = f'/tmp/{str(uuid.uuid4())}.mp4'  # for Recording
else:
    logger.warning('dstination type is not S3')

hosting_url = os.getenv("HOSTING_URL", "")
def get_bot_name():
    # Bot の名前が与えられなければ、タイムスタンプをつける
    datetime_created = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bot_name = os.getenv('BOT_NAME', f"Bot {datetime_created}")
    return bot_name
#################################

###### credentials ######
def get_credentials_from_role(is_run_on_container=True, roleArnToBeAssumed='arn:aws:iam::141160225184:role/Role-for-broadcast-container'):
    ####### set credentials as environment variables (required by API call made by streaming SDK)
    if is_run_on_container:
        url = 'http://169.254.170.2'
        url += os.getenv('AWS_CONTAINER_CREDENTIALS_RELATIVE_URI')
        
        with urllib.request.urlopen(url) as response:
            body = json.loads(response.read())
            # headers = response.getheaders()
            # status = response.getcode()
        access_key = body['AccessKeyId']
        secret_access_key = body['SecretAccessKey']
        session_token = body['Token']
    else:
        # create an STS client object that represents a live connection to the 
        # STS service
        sts_client = boto3.client('sts')
        
        # Call the assume_role method of the STSConnection object and pass the role
        # ARN and a role session name.
        assumed_role_object=sts_client.assume_role(
            RoleArn=roleArnToBeAssumed,
            RoleSessionName="AssumeRoleSession1",
            DurationSeconds=60*60*1 # 1 hour
        )
        
        # From the response that contains the assumed role, get the temporary 
        # credentials that can be used to make subsequent API calls
        credentials = assumed_role_object['Credentials']
        
        access_key = credentials['AccessKeyId']
        secret_access_key = credentials['SecretAccessKey']
        session_token = credentials['SessionToken']
    
    return {'access_key':access_key, 'secret_access_key':secret_access_key, 'session_token':session_token}

is_run_on_container = os.getenv('IS_RUN_ON_CONTAINER', 'True')
creds = get_credentials_from_role(eval(is_run_on_container))
os.environ['AWS_ACCESS_KEY_ID'] = creds['access_key']
os.environ['AWS_SECRET_ACCESS_KEY'] = creds['secret_access_key']
os.environ['AWS_SESSION_TOKEN'] = creds['session_token']
#########################

###### AppSync functions ######
def get_AppSync_client(url,access_key,secret_access_key,session_token,region='ap-northeast-1'):
    aws_auth = AWS4Auth(access_key,
        secret_access_key,
        region,
        'appsync',
        session_token=session_token)
    transport = RequestsHTTPTransport(url=API_URL, auth=aws_auth)#, retries=3)
    return Client(transport=transport)

appsyncClient = get_AppSync_client(API_URL,creds['access_key'],creds['secret_access_key'],creds['session_token'])

def appsync_execute(mutation, variables):
    try:
        res = appsyncClient.execute(mutation, variable_values=variables)
    except:
        pass
        # sleep(0.1)
        # try:
        #     logger.info('write appsync retry')
        #     res = appsyncClient.execute(mutation, variable_values=variables)
        # except:
        #     logger.error('failed to write appsync two times in a row')
    
def write_live_caption(caption,result_id):
    mutation = gql("""
    mutation MyMutation($input: CreateLiveCaptionInput!){
    createLiveCaption(input: $input) {
    transcription
    id
    meeting_id
    createdAt
    updatedAt
        }
    }
    """)
    variables = {
        "input":{
            "transcription":caption,
            "meeting_id":meeting_id,
            "id":result_id,
        }
    }
    
    appsync_execute(mutation, variables)

def write_chat(sender_name,time,content,attachment_name='',attachment_path=''):
    mutation = gql("""
    mutation MyMutation($input: CreateChatInput!){
    createChat(input: $input) {
    meeting_id
    sender_name
    time
    content
    id
    createdAt
    updatedAt
    attachment_name
    attachment_path
        }
    }
    """)
    variables = {
        "input":{
            "meeting_id":meeting_id,
            "sender_name":sender_name,
            "createdAt":time,
            "time":time, # obsolete
            "content":content,
            "attachment_name":attachment_name,
            "attachment_path":attachment_path,
        }
    }
    
    appsync_execute(mutation, variables)

def write_roster_info(attendee_name, status, _number_of_attendees):
    mutation = gql("""
    mutation MyMutation($input: CreateAttendeeInput!){
    createAttendee(input: $input) {
    meeting_id
    attendee_name
    status
    number_of_attendees
    createdAt
    updatedAt
        }
    }
    """)
    variables = {
        "input":{
            "meeting_id":meeting_id,
            "attendee_name":attendee_name,
            "status":status,
            "number_of_attendees":_number_of_attendees,
        }
    }
    
    appsync_execute(mutation, variables)
##################

class GracefulKiller:
    kill_now = False
    def __init__(self, ffmpeg_process):
        self.ffmpeg_process = ffmpeg_process
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum, frame):
        logger.info('Start graceful shutdown process...')
        try:
            logger.info('Stopping ffmpeg process gracefully...')
            self.ffmpeg_process.communicate(str.encode('q'), timeout=20)
            logger.info('Successfully stopped ffmpeg process gracefully.')
        except TimeoutExpired:
            logger.warning('Killing ffmpeg process...')
            ffmpeg_process.terminate()
            logger.warning('Successfully killed ffmpeg process.')
        if dst_type == 's3':
            logger.info('Archive a recording file...')
            client = boto3.client('s3')
            with open(tmp_file, 'rb') as f:
                res = client.put_object(
                    Body=f,
                    Bucket=s3_bucket,
                    Key=s3_key,
                    ContentType='video/mp4')
            logger.info(f'Successfully archived a recording file. [s3://{s3_bucket}/{s3_key}]')
        self.kill_now = True


class MyEventHandler(TranscriptResultStreamHandler):
    async def handle_transcript_event(self, transcript_event: TranscriptEvent):
        # This handler can be implemented to handle transcriptions as needed.
        logger.debug('event handler')
        results = transcript_event.transcript.results
        for result in results:
            result_id = result.result_id
            for alt in result.alternatives:
                write_live_caption(alt.transcript,result_id)
                logger.info(alt.transcript)
            if not result.is_partial:
                msg = {
                        'source_language_code': language_code, 
                        'meeting_id': meeting_id, 
                        'result_id': result_id, 
                        'transcript': alt.transcript
                    }
                request = {
                            'TopicArn': SNSTopicArn,
                            'Message': json.dumps(msg)
                        }
                # self.client.publish(**request)
                await self.sns_publish(request)
    
    async def sns_publish(self, request):
        self.client.publish(**request)

def get_time_from_metadata(data):
    date_time, ampm = re.findall("(?<=\[).+?(?=\])", data)[0].rsplit(' ',1) # ['September 14, 2021, 2:27', 'AM']
    time = datetime.datetime.strptime(date_time,'%B %d, %Y, %H:%M')
    if ampm=='PM':
        time+=datetime.timedelta(hours=12)
    return time # datetime object

async def get_new_chat_contents():
    global chat_count
    chat_contents = driver.find_elements(By.CLASS_NAME, 'ChatMessageList__messageContainer')
    ret = []
    if chat_count < len(chat_contents): # if there are new chat messages
        for content in chat_contents[chat_count:]:
            try:
                text_div = content.find_element(By.CLASS_NAME, 'Linkify')
                text = text_div.text
            except NoSuchElementException:
                logger.debug('chat without any text')
                text = ""
            except StaleElementReferenceException:
                logger.warning('stale element reference exception.')
            
            try:
                externalLink = content.find_element(By.CLASS_NAME, 'ExternalLink')
                attachment_name = externalLink.text
                attachment_path = externalLink.get_attribute('href')
            except (NoSuchElementException, StaleElementReferenceException) as e:
                attachment_name = ''
                attachment_path = ''
                logger.debug('find attachment failed')
                logger.debug(e)
            else:
                if content.find_elements(By.CLASS_NAME, 'ChatMessageUnfurl__right'):
                    logger.debug('url found')
                    text = '' # delete text to avoid duplication
            try:
                metadata_div = content.find_element(By.CLASS_NAME, 'ChatMessage__left')
                metadata = metadata_div.get_attribute("data-pre-plain-text") #"[September 14, 2021, 2:27 AM] Amazon Chime". this will be GMT
                sender_name = ' '.join(metadata.split()[5:])
                time = get_time_from_metadata(metadata)
            except:
                logger.error('chat metadata not found. this chat will NOT be written to the Dynamo DB.')
                sender_name = ''
                time = '1970-01-01T00:00:00.000Z'
            ret.append([sender_name, text, time, attachment_name, attachment_path])

        chat_count = len(chat_contents)
    return ret

async def get_roster_info():
    global number_of_attendees
    try:
        roster_container = driver.find_element(By.CLASS_NAME, 'MeetingRosterContainer')
    except NoSuchElementException:
        logger.warning("roster info is not ready yet")
        return
    
    number_of_attendees = get_number_of_attendees()
    if not number_of_attendees:
        return
    
    try:
        attendees = roster_container.find_elements(By.CLASS_NAME, 'MeetingRosterItem')[:number_of_attendees]
    except:
        logger.warning(f'could not find {number_of_attendees} attendees')
        return
    
    ret=[]
    for attendee in attendees:
        try:
            # get attendee's name
            attendee_name_field = attendee.find_element(By.CLASS_NAME, 'MeetingRosterItem__fullName')
            attendee_name = attendee_name_field.text
            logger.debug(attendee_name)
        except (NoSuchElementException, StaleElementReferenceException) as e:
            logger.warning(e)
            return

        ret.append(attendee_name)
    return ret # ex. ['Alice','Bob',...]

async def get_enter_exit_records():
    global attendees_latest
    attendee_list = await get_roster_info()
    logger.debug(f'attendee list: {attendee_list}')
    ret = []
    if not attendee_list:
        logger.debug('No attendee found')
        return ret
    attendees_cur = set(attendee_list)
    new_joiners = attendees_cur - attendees_latest
    left_people = attendees_latest - attendees_cur

    if new_joiners or left_people:
        attendees_latest = attendees_cur
        for new_joiner in new_joiners:
            ret.append([new_joiner,'joined'])
        for left_person in left_people:
            ret.append([left_person,'left'])
    return ret

def get_number_of_attendees():
    try:
        number_of_attendees_div = driver.find_element(By.CLASS_NAME, 'SidebarHeader__text')
        raw_text = number_of_attendees_div.text # attendees (#)
        logger.debug('get # of attendees successfully')
    except (NoSuchElementException, StaleElementReferenceException) as e:
        logger.debug('# of attendees not ready yet')
        logger.debug(e)
        return
    
    if len(raw_text) > len('attendees'): # raw text can be only 'attendees' (without any number) right after the meeting started
        _number_of_attendees = int(re.search("(?<=\().*?(?=\))", raw_text).group(0)) # get the number within the parenthesis
        logger.debug(f'# of attendees:{_number_of_attendees}')
        return _number_of_attendees
    

def check_meeting_status():
    ###################################################
    # Move the contents in the original infinite loop #
    ###################################################

    # check console log
    for entry in driver.get_log('browser'):
        if entry['level'] == 'WARNING':
            logger.warning(entry)
        else:
            logger.info(entry)

    # check page crash
    try:
        current_url = driver.current_url
        logger.debug('Browser is not crashed.')
    except WebDriverException as e:
        logger.error(e)
        driver.get(src_url)
        logger.info('Successfully reloaded the browser.')
        current_url = src_url

    # check chime meeting status
    try:
        end_container = driver.find_element(By.CLASS_NAME, 'MeetingEndContainer')
    except NoSuchElementException:
        return
    else:
        logger.info('This meeting is ended.')
        killer.exit_gracefully(signal.SIGTERM, None)
        # force quit the loop (TODO: can be improved)
        # loop.close()
        driver.quit()
        display.stop()
        sys.exit(0)
    
async def infinite_loop():
    # sleep(2)
    while True:
        records = await get_enter_exit_records()
        for record in records:
            logger.info(f'new record: {record}')
            attendee_name = record[0]
            status = record[1]
            write_roster_info(attendee_name, status, number_of_attendees)
        chats = await get_new_chat_contents()
        for chat in chats:
            logger.info(f'new chat: {chat}')
            sender_name = chat[0]
            content = chat[1]
            # create 'time' var which is type of AWSDateTime
            time = chat[2].isoformat() +'.000Z'
            attachment_name = chat[3]
            attachment_path = chat[4]
            write_chat(sender_name, time, content, attachment_name, attachment_path)
        check_meeting_status()
        await asyncio.sleep(3)

async def mic_stream():
    logger.debug('mic_stream called')
    # This function wraps the raw input stream from the microphone forwarding
    # the blocks to an asyncio.Queue.
    loop = asyncio.get_event_loop()
    input_queue = asyncio.Queue()

    def callback(indata, frame_count, time_info, status):
        loop.call_soon_threadsafe(input_queue.put_nowait, (bytes(indata), status))

    # Be sure to use the correct parameters for the audio stream that matches
    # the audio formats described for the source language you'll be using:
    # https://docs.aws.amazon.com/transcribe/latest/dg/streaming.html
    stream = sounddevice.RawInputStream(
        channels=1,
        samplerate=audio_samplerate,
        callback=callback,
        blocksize=1024 * 2,
        dtype="int16",
    )
    # Initiate the audio stream and asynchronously yield the audio chunks
    # as they become available.
    with stream:
        while True:
            indata, status = await input_queue.get()
            yield indata, status


async def write_chunks(stream):
    logger.debug('write_chunks')
    # This connects the raw audio chunks generator coming from the microphone
    # and passes them along to the transcription stream.
    async for chunk, status in mic_stream():
        await stream.input_stream.send_audio_event(audio_chunk=chunk)
    await stream.input_stream.end_stream()


async def basic_transcribe(killer,region="ap-northeast-1"):
    logger.debug('basic_transcribe called')
    # Set up our client with our chosen AWS region
    client = TranscribeStreamingClient(region=region)
    logger.debug('client set up')
    # Start transcription to generate our async stream
    stream = await client.start_stream_transcription(
        language_code=language_code,
        media_sample_rate_hz=audio_samplerate,
        media_encoding="pcm",
        # show_speaker_label = True # only available in English as of Aug. 2021
    )
    logger.debug('after stream')
    # Instantiate our handler and start processing events
    handler = MyEventHandler(stream.output_stream)
    logger.debug('event handler created')
    handler.client = boto3.client('sns',region_name=region)
    await asyncio.gather(write_chunks(stream), handler.handle_events(), infinite_loop())

def update_meeting_status(meeting_id, lambda_arn, status="Running"):
    def get_task_id():
        url = os.getenv('ECS_CONTAINER_METADATA_URI_V4') + '/task'
        with urllib.request.urlopen(url) as response:
            body = json.loads(response.read())
        task_id = body['TaskARN'].split('/')[-1]
        return task_id
    
    region = lambda_arn.split(':')[3]
    client = boto3.client('lambda', region_name=region)
    #Lambdaのevent変数に入れる値
    query = {
        "id": meeting_id,
        "status": status,
        "task_id":get_task_id()
    }
    
    #Lambdaを実行
    response = client.invoke(
        FunctionName=lambda_arn,
        LogType='Tail',
        Payload= json.dumps(query)
    )
    
    status_code = response['StatusCode']
    # res = response['Payload'].read()
    logger.debug(status_code)
    logger.debug(response)
    if status_code != 200:
        logger.warning('Error occured when updating meeting status!!')

def get_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--autoplay-policy=no-user-gesture-required')
    options.add_argument(f'--window-size={screen_width},{screen_height}')
    options.add_argument('--start-fullscreen')
    options.add_experimental_option("excludeSwitches", ['enable-automation'])
    options.add_argument('—use-fake-device-for-media-stream')
    options.add_argument('--use-file-for-fake-audio-capture=./silence.wav') # Add to activate microphone
    options.add_argument("--use-fake-ui-for-media-stream")
    options.add_argument("--disable-infobars")
    # options.add_argument("--enable-automation")
    options.add_argument('--disable-extensions')
    options.add_argument("--disable-browser-side-navigation")
    options.add_argument("--disable-gpu")
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--ignore-ssl-errors')
    # if src_type == 'chime_webclient':
    options.add_argument('--use-fake-device-for-media-stream')
    options.add_experimental_option("prefs", {
        "protocol_handler.allowed_origin_protocol_pairs": {"https://app.chime.aws": {"chime": True} },
        "profile.default_content_setting_values.media_stream_mic": 1,
        "profile.default_content_setting_values.notifications": 2
    })
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    capabilities = DesiredCapabilities.CHROME
    capabilities['loggingPrefs'] = { 'browser':'ALL' }
    
    return webdriver.Chrome(options=options, desired_capabilities=capabilities)

def move_mouse_cursor(driver):
    # Move mouse out of the way so it doesn't trigger the "pause" overlay on the video tile
    actions = ActionChains(driver)
    wait = WebDriverWait(driver, 5)
    wait.until(visibility_of_element_located((By.TAG_NAME, 'html')))
    whole_page = driver.find_element(By.TAG_NAME, "html")
    actions.move_to_element_with_offset(whole_page, 0, 0)
    # actions.move_by_offset(0, int(screen_height) - 1)
    actions.perform()
    logger.debug("Moved mouse cursor.")

def hello_from_bot(driver, wait, contents="Hello! I'm a bot from Amazon CLiCS."):
    wait.until(visibility_of_element_located((By.CLASS_NAME, "DraftEditor-editorContainer")))
    DraftEditor_editorContainer = driver.find_element(By.CLASS_NAME, "DraftEditor-editorContainer")
    chat_input_area = DraftEditor_editorContainer.find_element(By.TAG_NAME, "div").find_element(By.TAG_NAME, "div").find_element(By.TAG_NAME, "div").find_element(By.TAG_NAME, "div").find_element(By.TAG_NAME, "span")
    chat_input_area.send_keys(contents + Keys.ENTER)

def send_bot(driver, hosting_url):
    wait = WebDriverWait(driver, 5)
    wait.until(visibility_of_element_located((By.CSS_SELECTOR, '.InputBox.AnonymousJoinContainer__nameFieldInputBox')))
    # Modify Bot Name
    input_box = driver.find_element(By.XPATH, "//div[@class='InputBox AnonymousJoinContainer__nameFieldInputBox']/div/input")
    bot_name = get_bot_name()
    input_box.send_keys(bot_name)
    next_button = driver.find_element(By.CSS_SELECTOR, '.Button.Button__primary.AnonymousJoinContainer__nextButton')
    next_button.click()
    logger.debug("Successfully joined to the meeting room.")
    # Enable Audio Devices
    audio_button = wait.until(visibility_of_element_located((By.CSS_SELECTOR, '.AudioSelectModalContainer__voipButton')))
    audio_button.click()
    logger.debug("Successfully enabled fake audio devices.")
    # Mute Fake Audio Input
    try:
        mute_button = wait.until(visibility_of_element_located((By.CSS_SELECTOR, '.MeetingControlButton.MeetingControlButton--micActive')))
        mute_button.click()
    except:
        logger.warning('mute button click failed') # this can happen if the 'large meeting setting' on Chime is enabled
    
    message = f"Hello! I'm \"{bot_name}\" from Amazon CLiCS. I'm recording this meeting and delivering live caption on the following URL: {hosting_url}"
    try:
        hello_from_bot(driver, wait, message)
    except:
        logger.error("Bot could not send the hello message. Does the meeting allow 'anyone' to join the meeting?")
        sys.exit(1)

def get_ffmpeg_process(driver):
    logger.debug("Preparing video & audio streams")
    video_stream = ffmpeg.input(
        f':{display.display}',
        f='x11grab',
        s=screen_resolution,
        r=video_framerate,
        draw_mouse=0,
        thread_queue_size=1024).filter('fps', fps=filter_framerate, round='up')
    
    audio_stream = ffmpeg.input(
        'default',
        f='pulse',
        ac=2,
        thread_queue_size=1024)
    
    if dst_type == 's3':
        logger.debug("dst_type = S3")
        if output_format == 'flac':
            out = ffmpeg.output(
                audio_stream,
                tmp_file,
                f='flac',
                loglevel='error',
                threads=thread_num,
                filter_complex=f'adelay=delays={audio_delays}|{audio_delays}',
                acodec='flac',
                sample_fmt='s16',
                strict='-2',
                #audio_bitrate=audio_bitrate,
                ac=audio_channels,
                ar=audio_samplerate,
            )
        else:
            out = ffmpeg.output(
                video_stream,
                audio_stream,
                tmp_file,
                f=output_format,
                loglevel='error',
                threads=thread_num,
                vcodec='libx264',
                pix_fmt='yuv420p',
                vprofile='main',
                preset='veryfast',
                x264opts='nal-hrd=cbr:no-scenecut',
                video_bitrate=video_bitrate,
                #minrate=video_minrate,
                #maxrate=video_maxrate,
                #bufsize=video_bufsize,
                g=video_gop,
                audio_sync=100,
                filter_complex=f'adelay=delays={audio_delays}|{audio_delays}',
                acodec=audio_codec,
                audio_bitrate=audio_bitrate,
                ac=audio_channels,
                ar=audio_samplerate,
            )
    else:
        out = ffmpeg.output(
            video_stream,
            audio_stream,
            dst_url,
            f='flv',
            loglevel='error',
            threads=thread_num,
            vcodec='libx264',
            pix_fmt='yuv420p',
            vprofile='main',
            preset='veryfast',
            x264opts='nal-hrd=cbr:no-scenecut',
            video_bitrate=video_bitrate,
            #minrate=video_minrate,
            #maxrate=video_maxrate,
            #bufsize=video_bufsize,
            g=video_gop,
            audio_sync=100,
            filter_complex=f'adelay=delays={audio_delays}|{audio_delays}',
            acodec='aac',
            audio_bitrate=audio_bitrate,
            ac=audio_channels,
            ar=audio_samplerate,
        )
    out = out.overwrite_output()
    logger.info(out.compile())
    logger.info('Launch ffpmeg process...')
    ffmpeg_process = out.run_async(pipe_stdin=True)
    return ffmpeg_process

if __name__=='__main__':
    chat_count = 0
    attendees_latest = set()
    
    display = Display(visible=False, size=(screen_width, screen_height), color_depth=color_depth)
    logger.info('Launch a virtual display.')
    display.start()

    logger.info("Successfully launched a virtual display.")
    driver = get_driver()
    logger.info(f'Open {src_url} ...')
    driver.get(src_url)
    
    move_mouse_cursor(driver)
    
    send_bot(driver, hosting_url)
    update_meeting_status(meeting_id, lambda_arn, status="Running")
    ffmpeg_process = get_ffmpeg_process(driver)

    killer = GracefulKiller(ffmpeg_process)
    
    loop = asyncio.get_event_loop()    
    loop.run_until_complete(basic_transcribe(killer))
