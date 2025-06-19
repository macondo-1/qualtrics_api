import http.client
import mimetypes
import base64
import credentials as cred
import json
import csv
import pandas as pd
from pathlib import Path
import zipfile

cur_path = Path(__file__).resolve().parent
surveys_info_file_path = 'qualtrics_surveys_info.csv'
zip_downloads = cur_path.joinpath('zip_files')
csv_files_dir = cur_path.joinpath('csv_files')

def get_bearer_token(scopes):
    """
    makes the first api call to retrieve the oauth token
    """
    #create the Base64 encoded basic authorization string
    clientID=cred.client_id
    clientsecret=cred.client_secret
    datacenter_id = cred.datacenter_id
    auth = "{0}:{1}".format(clientID, clientsecret)
    encodedBytes=base64.b64encode(auth.encode("utf-8"))
    authStr = str(encodedBytes, "utf-8")

    #create the connection 
    conn = http.client.HTTPSConnection("{}.qualtrics.com".format(datacenter_id))
    body = "grant_type=client_credentials&scope={}".format(scopes)
    headers = {
      'Content-Type': 'application/x-www-form-urlencoded'
    }
    headers['Authorization'] = 'Basic {0}'.format(authStr)

    #make the request
    conn.request("POST", "/oauth2/token", body, headers)
    res = conn.getresponse()
    data = res.read()

    print(data.decode("utf-8"))

def make_api_call(method, api_call, body = '', response_type = 'json'):
    """
    makes an api call and prints it as a json
    returns a json
    """
    datacenter_id = cred.datacenter_id
    bearer_token = cred.bearer_token
    # create the request
    conn = http.client.HTTPSConnection("{}.qualtrics.com".format(datacenter_id))
    headers = {
      'Authorization': 'Bearer {}'.format(bearer_token),
      "Content-Type": "application/json"
    }

    # make the request
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
    surveys_data_list = surveys_data_dict['result']['elements']

    while surveys_data_dict['result']['nextPage']:
        api_call = surveys_data_dict['result']['nextPage'].split('/')[-1]
        surveys_data_dict = make_api_call(method, api_call)
        surveys_data_list.extend(surveys_data_dict['result']['elements'])

    #surveys_data
    with open('qualtrics_surveys_info.csv', mode='w', newline='') as file:
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
    df = pd.read_csv(surveys_info_file_path)
    df['progress_id'] = df['progress_id'].astype(str)
    row = df[df.id == survey_id].index[0]
    column = 'progress_id'
    df.at[row,'progress_id'] = progress_id
    df.to_csv(surveys_info_file_path, index=False)
  
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


#get_bearer_token('read:survey_responses')
#get_all_surveys_info()

#start_all_downloads()
#check_download_readyness()
#download_ready_file()
#download_all_available_files()
unzip_all_files()
