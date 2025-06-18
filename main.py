import http.client
import mimetypes
import base64

#create the Base64 encoded basic authorization string
clientID="{Client ID}"
clientsecret="{Client Secret}"
auth = "{0}:{1}".format(clientID, clientsecret)
encodedBytes=base64.b64encode(auth.encode("utf-8"))
authStr = str(encodedBytes, "utf-8")

#create the connection 
conn = http.client.HTTPSConnection("st3.qualtrics.com")
body = "grant_type=client_credentials&scope=read:users"
headers = {
  'Content-Type': 'application/x-www-form-urlencoded'
}
headers['Authorization'] = 'Basic {0}'.format(authStr)

#make the request
conn.request("POST", "/oauth2/token", body, headers)
res = conn.getresponse()
data = res.read()

print(data.decode("utf-8"))
