import http.client
import mimetypes
import base64
import credentials as cred
import json
import csv


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

def make_api_call(api_call):
    """
    makes an api call and prints it as a json
    returns a json
    """
    datacenter_id = cred.datacenter_id
    bearer_token = cred.bearer_token
    # create the request
    conn = http.client.HTTPSConnection("{}.qualtrics.com".format(datacenter_id))
    body = ''
    headers = {
      'Authorization': 'Bearer {}'.format(bearer_token),
      "Content-Type": "application/json"
    }

    # make the request
    conn.request("GET", "/API/v3/{}".format(api_call), body, headers)
    res = conn.getresponse()
    data = res.read()
    json_data = json.loads(data.decode("utf-8"))
    print(json_data)

    return json_data

def get_all_surveys_info():
    """
    Iterates over all the response pages and save them as a csv file
    """

    surveys_data_dict = make_api_call('surveys')
    surveys_data_list = surveys_data_dict['result']['elements']

    while surveys_data_dict['result']['nextPage']:
        api_call = surveys_data_dict['result']['nextPage'].split('/')[-1]
        surveys_data_dict = make_api_call(api_call)
        surveys_data_list.extend(surveys_data_dict['result']['elements'])

    #surveys_data
    with open('qualtrics_surveys_info.csv', mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=surveys_data_list[0].keys())
        writer.writeheader()
        writer.writerows(surveys_data_list)


#get_bearer_token('read:users manage:surveys')
get_all_surveys_info()