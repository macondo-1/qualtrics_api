import http.client
import mimetypes
import base64
import credentials as cred
import json
import csv
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
import zipfile
import time
import re
import os
import requests
from functools import wraps
from urllib.parse import urlparse
from typing import Iterator

cur_path = Path(__file__).resolve().parent
load_dotenv(cur_path / ".env")

credentials_path = cur_path.joinpath('credentials.csv')

zip_downloads = cur_path.joinpath('files', 'zip_files')
csv_files_dir = cur_path.joinpath('files', 'csv_files')
# move these paths outside the API handler
surveys_info_file_path = 'qualtrics_surveys_info.csv'
projects_path = Path('/Users/home/Documents/sis_international/python/utilities/sis_international_files/projects')

class QualtricsClient:
    BASE_URL = 'https://sjc1.qualtrics.com/API/v3/'

    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url
        self._allowed_host = urlparse(base_url).netloc

        self.ratelimit_remaining = None # CHECK: can we implement ratelimit for qualtrics?
        self.bearer_token = os.environ.get('BEARER_TOKEN')
        self.client_id = os.environ.get('CLIENT_ID')
        self.client_secret = os.environ.get('CLIENT_SECRET')
        self.session = requests.Session()
        #create the Base64 encoded basic authorization string
        auth = "{0}:{1}".format(self.client_id, self.client_secret)
        encodedBytes=base64.b64encode(auth.encode("utf-8"))
        authStr = str(encodedBytes, "utf-8")
        self.session.headers.update({
                                    'Authorization': 'Basic {0}'.format(authStr),
                                    "Content-Type": "application/x-www-form-urlencoded"
                                    })
        data = 'grant_type=client_credentials&scope=manage:all'
        self.url = 'https://sjc1.qualtrics.com/oauth2/token'
        response = self.post(self.url, data=data)
        response_json = response.json()
        self.access_token = response_json['access_token']
        self.session.headers.update({
                                    'Authorization': 'Bearer {}'.format(self.access_token),
                                    "Content-Type": "application/json"
                                    })

    def _check_host(self, url):
        """
        Raises if url's host isn't the same host as base_url.

        self.session carries the OAuth bearer token as a default header,
        so any request issued through it -- an absolute-URL endpoint or a
        pagination `nextPage` link taken from a prior response -- attaches
        the live credential to whatever host is requested. Checked before
        every such use rather than trusted implicitly.
        """
        host = urlparse(url).netloc
        if host != self._allowed_host:
            raise ValueError(
                f"Refusing to send credentialed request to unexpected host "
                f"{host!r} (expected {self._allowed_host!r}): {url!r}"
            )

    def _request(self, method, endpoint, **kwargs):
        # if self.ratelimit_remaining is not None and int(self.ratelimit_remaining) <= RATELIMIT_THRESHOLD:
        #     raise RuntimeError(f"Daily rate limit nearly exhausted: {self.ratelimit_remaining} remaining")

        if endpoint.startswith("https"):
            url = endpoint
            self._check_host(url)
        else:
            url = f"{self.base_url}/{endpoint}"

        response = self.session.request(method, url, **kwargs)
        response.raise_for_status()
        # self.ratelimit_remaining = response.headers.get('X-Ratelimit-App-Global-Day-Remaining')
        return response

    def paginate(func) -> Iterator[dict]:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            response = func(self, *args, **kwargs)
            while True:
                body = response.json()
                yield from body.get("result", []).get("elements")
                next_link = body.get("result", {}).get("nextPage")
                if not next_link:
                    break
                self._check_host(next_link)
                response = self.session.get(next_link)
        return wrapper

    def get(self, endpoint) -> requests.Response:
        return self._request("GET", endpoint)

    get_paginated = paginate(get)

    def post(self, endpoint, data):
        return self._request("POST", endpoint, data=data)

    def get_all_surveys_info(self) -> list:
        endpoint = 'surveys'
        result = self.get_paginated(endpoint)
        surveys_data_list = list(result)
        return surveys_data_list

    def get_survey_metadata(self, survey_id:str):
        endpoint = 'survey-definitions/{0}/metadata'.format(survey_id)
        result = self.get(endpoint)
        return result

    def start_survey_answers_export(self, survey_id:str) -> str:
        """
        sends a POST request to start the download of a survey responses
        returns the progress id
        """

        endpoint = 'surveys/{survey_id}/export-responses'.format(survey_id=survey_id)
        body = "{\n  \"format\": \"csv\"\n}"

        response = self.post(endpoint=endpoint, data=body).json()
        progress_id = response['result']['progressId']

        return progress_id

    def get_survey_answers_export_file_id(self, survey_id:str, progress_id:str) -> str: # -> str
        """
        returns the file_id if available
        """

        endpoint = 'surveys/{0}/export-responses/{1}'.format(survey_id, progress_id)

        response = self.get(endpoint=endpoint).json()

        # CHECK: move the try block out of here
        try:
            file_id = response['result']['fileId']
        except Exception as e:
            print(e)
            file_id = None

        return file_id   

    def download_zip_and_csv_files(self, survey_id:str, file_id:str) -> None:
        """
        Downloads the zip file of the ready-to-be-downloaded survey
        returns the Path to the saved file
        """

        endpoint = 'surveys/{survey_id}/export-responses/{file_id}/file'.format(survey_id=survey_id, file_id=file_id)
        data = self.get(endpoint=endpoint)

        file_name = '{}_responses.zip'.format(survey_id)
        zip_file_name = zip_downloads.joinpath(file_name)
        with open(zip_file_name, 'wb') as f:
            f.write(data.content)

        with zipfile.ZipFile(zip_file_name, 'r') as zip_ref:
            zip_ref.extractall(csv_files_dir)

    def download_survey_answers(self, survey_id:str, ):
        """
        Downloads a single survey
        This function follows the complete process:

        1. start download
        2. wait for file to be ready to download
        3. downloads the file
        4. saves it as a zip file in the zip_files folder
        5. unzips file and saves it to csv_files folder
        """
        progress_id = self.start_survey_answers_export(survey_id=survey_id)

        loop = 1
        file_id = None
        while not file_id:
            print('entered loop')
            file_id = self.get_survey_answers_export_file_id(survey_id=survey_id, progress_id=progress_id)
            print('file_id:', file_id)
            if file_id:
                break
            print('waaiting 5 seconds...')
            time.sleep(5)
            print('loop {} ended'.format(loop))
            loop += 1

            # So the loop is not infinite
            if loop > 4:
                print('Too many loops, try again later...')
                break

        self.download_zip_and_csv_files(survey_id=survey_id, file_id=file_id)
        print('file succesfully saved!')

def read_credentials():
    global credentials_path
    with open(credentials_path, 'r', newline='') as csvfile:
        dict_reader = csv.DictReader(csvfile)
        for row in dict_reader:
            client_id = row['client_id']
            client_secret = row['client_secret']
            datacenter_id = row['datacenter_id']
            bearer_token = row['bearer_token']

        credentials = {
                'client_id':client_id,
                'client_secret':client_secret,
                'datacenter_id':datacenter_id,
                'bearer_token':bearer_token
            }
    return credentials

def update_credentials():
    """
    saves newly created bearer token
    """
    global credentials_path
    credentials = read_credentials()

    bearer_token = get_bearer_token()

    with open(credentials_path, 'w', newline='') as csvfile:
        fieldnames = ['client_id','client_secret','datacenter_id','bearer_token']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        credentials['bearer_token'] = bearer_token
        writer.writerow(credentials)

def get_bearer_token(scopes = 'manage:all'):
    """
    makes the first api call to retrieve the oauth token
    default scopes = manage:all
    """

    credentials = read_credentials()

    #create the Base64 encoded basic authorization string
    auth = "{0}:{1}".format(credentials['client_id'], credentials['client_secret'])
    encodedBytes=base64.b64encode(auth.encode("utf-8"))
    authStr = str(encodedBytes, "utf-8")

    #create the connection 
    conn = http.client.HTTPSConnection("{}.qualtrics.com".format(credentials['datacenter_id']))
    body = "grant_type=client_credentials&scope={}".format(scopes)
    headers = {
      'Content-Type': 'application/x-www-form-urlencoded'
    }
    headers['Authorization'] = 'Basic {0}'.format(authStr)

    #make the request
    conn.request("POST", "/oauth2/token", body, headers)
    res = conn.getresponse()
    data = res.read()
    data = json.loads(data.decode("utf-8"))
    access_token = data['access_token']

    return access_token

def make_api_call(method, api_call, body = '', response_type = 'json'):
    """
    makes an api call and prints it as a json
    returns a json
    """

    credentials = read_credentials()

    # create the request
    conn = http.client.HTTPSConnection("{}.qualtrics.com".format(credentials['datacenter_id']))
    headers = {
      'Authorization': 'Bearer {}'.format(credentials['bearer_token']),
      "Content-Type": "application/json"
    }

    # make the request
    conn.request(method, "/API/v3/{}".format(api_call), body, headers)
    res = conn.getresponse()

    if res.status != 200:
        print('updating bearer token...')
        update_credentials()
        print('bearer token updated succesfully')
        credentials = read_credentials()
        headers['Authorization'] = 'Bearer {}'.format(credentials['bearer_token'])
        conn.request(method, "/API/v3/{}".format(api_call), body, headers)
        res = conn.getresponse()

    data = res.read()
    if response_type == 'json':
      data = json.loads(data.decode("utf-8"))

    return data

def get_all_surveys_info():
    """
    Iterates over all the response pages and save them as a csv file
    """
    method = 'GET'
    surveys_data_dict = make_api_call(method, 'surveys')
    print(surveys_data_dict)
    surveys_data_list = surveys_data_dict['result']['elements']

    while surveys_data_dict['result']['nextPage']:
        api_call = surveys_data_dict['result']['nextPage'].split('/')[-1]
        surveys_data_dict = make_api_call(method, api_call)
        surveys_data_list.extend(surveys_data_dict['result']['elements'])

    #surveys_data
    with open(surveys_info_file_path, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=surveys_data_list[0].keys())
        writer.writeheader()
        writer.writerows(surveys_data_list)

def start_response_export(survey_id):
    """
    sends a POST request to start the download of a survey responses
    retrieves the export progress id and saves it for later use
    """
    global surveys_info_file_path
    method = 'POST'
    api_call = 'surveys/{survey_id}/export-responses'.format(survey_id=survey_id)
    body = "{\n  \"format\": \"csv\"\n}"
    response = make_api_call(method, api_call, body)
    progress_id = response['result']['progressId']

    return progress_id
    # df = pd.read_csv(surveys_info_file_path)
    # df['progress_id'] = df['progress_id'].astype(str)
    # row = df[df.id == survey_id].index[0]
    # column = 'progress_id'
    # df.at[row, column] = progress_id
    # df.to_csv(surveys_info_file_path, index=False)
  
def start_all_downloads():
    """
    Iterates over all surveys without a progress_id and starts the download
    """
    global surveys_info_file_path
    df = pd.read_csv(surveys_info_file_path)
    df = df[~pd.notnull(df.progress_id)]
    for survey_id in df.id:
        try:
          start_response_export(survey_id)
        except Exception as e:
            print(e)
        
def check_download_readyness(survey_id,progress_id):
    """
    checks if the download file is ready to download
    returns the file_id
    """
    global surveys_info_file_path
    method = 'GET'
    api_call = 'surveys/{survey_id}/export-responses/{progress_id}'.format(survey_id=survey_id, progress_id=progress_id)
    response = make_api_call(method, api_call)

    try:
        file_id = response['result']['fileId']
    except Exception as e:
        print(e)
        file_id = None

    return file_id

def download_ready_file(survey_id, file_id):
    """
    Downloads the zip file of the ready-to-be-downloaded survey
    """
    method = 'GET'
    api_call = 'surveys/{survey_id}/export-responses/{file_id}/file'.format(survey_id=survey_id, file_id=file_id)
    data = make_api_call(method, api_call,response_type='file')

    file_name = '{}_responses.zip'.format(survey_id)
    zip_file_name = zip_downloads.joinpath(file_name)
    with open(zip_file_name, 'wb') as f:
        f.write(data)

def download_all_available_files():
    """
    Iterates over the files info and downloads every survey that is ready
    """
    global surveys_info_file_path
    df = pd.read_csv(surveys_info_file_path)
    df_remaining_files = df[~pd.notnull(df.file_id)]
    for item in df_remaining_files.itertuples():
        survey_id = item.id 
        progress_id = item.progress_id
        file_id = check_download_readyness(survey_id,progress_id)

        if file_id:
            row = df[df.id == survey_id].index[0]
            column = 'file_id'
            df.at[row, column] = file_id
            df.to_csv(surveys_info_file_path, index=False)
            download_ready_file(survey_id, file_id)

def unzip_all_files():
    """
    Iterates over the downloaded zip files and unzips them in another directory
    """
    global csv_files_dir
    global zip_downloads
    for zip_file_name in zip_downloads.glob('*.zip'):
      with zipfile.ZipFile(zip_file_name, 'r') as zip_ref:
        zip_ref.extractall(csv_files_dir)

def unzip_single_file(survey_id):
    pattern = '{}*'.format(survey_id)
    for zip_file_name in zip_downloads.glob(pattern):
      with zipfile.ZipFile(zip_file_name, 'r') as zip_ref:
        zip_ref.extractall(csv_files_dir)

def download_single_survey_whole_process(survey_id):
    """
    Downloads a single survey
    This function follows the complete process:

    1. start download
    2. wait for file to be ready to download
    3. downloads the file
    4. saves it as a zip file in the zip_files folder
    5. unzips file and saves it to csv_files folder
    """

    progress_id = start_response_export(survey_id=survey_id)

    loop = 1
    file_id = None
    while not file_id:
        print('entered loop')
        file_id = check_download_readyness(survey_id,progress_id)
        print('file_id:', file_id)
        if file_id:
            break
        print('waaiting 5 seconds...')
        time.sleep(5)
        print('loop {} ended'.format(loop))
        loop += 1

        # So the loop is not infinite
        if loop > 4:
            print('Too many loops, try again later...')
            break

    download_ready_file(survey_id, file_id)
    unzip_single_file(survey_id)
    print('file succesfully saved!')

def get_survey_responses(file_name):
    """
    Reads the downloaded survey responses
    returns 
    """
    
    filename = csv_files_dir.joinpath(file_name)
    df = pd.read_csv(filename, header=1, low_memory=False) 
    df = df[1:]
    df['End Date'] = pd.to_datetime(df['End Date']).dt.date.apply(lambda x: x.strftime('%Y%m%d'))
    
    return df

def update_json_with_qualtrics(path):
    """
    Updates the survey json with responses counted from qualtrics
    """
    with open(path, 'r') as file:
        json_file = json.load(file)
    json_file['qualtrics']['collectors'] = []

    # Consider moving this out of this function
    survey_id = json_file['qualtrics']['survey_id']
    download_single_survey_whole_process(survey_id)
    # --------

    file_name = json_file['qualtrics']['name']
    file_name = '{}.csv'.format(file_name)
    survey_responses = get_survey_responses(file_name)
    unique_collectors = survey_responses['source'].unique()

    collectors = []
    for unique_collector in unique_collectors:
        project_dict = {}
        
        #project_dict['responses_counts'] = {}


        if str(unique_collector) == 'nan':
            project_dict['name'] = 'nan'
            counts_dict = survey_responses[survey_responses['source'].isna()]['End Date'].value_counts().to_dict()
            counts_dict['total'] = sum(counts_dict.values())
            project_dict['responses_counts'] = counts_dict
            collectors.append(project_dict)

        else:
            project_dict['name'] = unique_collector
            counts_dict = survey_responses[survey_responses['source'] == unique_collector]['End Date'].value_counts().to_dict()
            counts_dict['total'] = sum(counts_dict.values())
            project_dict['responses_counts'] = counts_dict
            collectors.append(project_dict)

    json_file['qualtrics']['collectors'] = collectors

    with open(path, 'w') as file:
        json.dump(json_file, file, indent=4)

def update_jsons_with_qualtrics(working_qualtrics_jsons):
    """
    Updates all jsons from qualtrics
    """

    for path in working_qualtrics_jsons:
        try:
            update_json_with_qualtrics(path)
            print('done: ', path.name,'\n')
        except Exception as e:
            print('failed: ', path.name)
            print(e)

def get_working_qualtrics_jsons():
    """
    Gets all json files containing qualtrics in their keys
    returns a list of paths 
    """

    working_qualtrics_jsons = []
    for x in projects_path.iterdir():
        if x.is_dir():
            file_path = x.joinpath('{}.json'.format(x.name))

            if file_path.exists():

                with open(file_path) as file:
                    project_dict = json.load(file)
                    if 'qualtrics' in project_dict.keys():
                        working_qualtrics_jsons.append(file_path)

    return working_qualtrics_jsons

# working_qualtrics_jsons = get_working_qualtrics_jsons()
# working_qualtrics_jsons = [x for x in working_qualtrics_jsons if '195132' in str(x)]
# for x in working_qualtrics_jsons:
#     print(x.name)
# update_jsons_with_qualtrics(working_qualtrics_jsons)

def main():
    project_numbers = input('Please provide project numbers to update separated by commas\n(Click Enter/Return to update all):')
    project_numbers = project_numbers.split(',')
    pattern = '|'.join(project_numbers)
    pattern = re.compile(pattern)
    working_qualtrics_jsons = get_working_qualtrics_jsons()

    if project_numbers:
        working_qualtrics_jsons = [x for x in working_qualtrics_jsons if re.search(pattern, str(x))]
        if not working_qualtrics_jsons:
            print('No json found')
            exit()
    update_jsons_with_qualtrics(working_qualtrics_jsons)

if __name__ == '__main__':
    survey_id = 'SV_00bOwXOeW1OzVRQ'
    handler = QualtricsClient()
    handler.download_survey_answers(survey_id)