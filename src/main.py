from dotenv import load_dotenv
from flask import Flask, redirect, request
import secrets
import string
import hashlib
import urllib.parse
import os
import base64
import requests  # Import the requests library for making POST requests

load_dotenv()

client_id = os.getenv("CLIENT_ID")
client_secret = os.getenv("CLIENT_SECRET")


def generate_random_string(length):
    possible_chars = string.ascii_letters + string.digits  # A-Z, a-z, 0-9
    return ''.join(secrets.choice(possible_chars) for _ in range(length))


# Step 1. Generate the code verifier
code_verifier = generate_random_string(64)

# Step 2. Generate transform (hash) using SHA256
hash_sha256 = hashlib.sha256(code_verifier.encode('utf-8')).digest()

# Step 3. Generate base64 representation of generated SHA256 hash
auth_base64 = base64.urlsafe_b64encode(hash_sha256).decode('utf-8').rstrip('=')

redirect_uri = "http://localhost:8888/callback"
auth_url = "https://accounts.spotify.com/authorize"
# TODO: Adjust for correct scope
scope = "user-read-private user-read-email user-top-read"
params = {
    'response_type': 'code',
    'client_id': client_id,
    'scope': scope,
    'code_challenge_method': 'S256',
    'code_challenge': auth_base64,
    'redirect_uri': redirect_uri,
}

# Generate the query string
auth_url_with_params = auth_url + "?" + urllib.parse.urlencode(params)

app = Flask(__name__)

# Route to redirect user to Spotify's authorization page


@app.route('/')
def redirect_to_spotify():
    return redirect(auth_url_with_params)


@app.route('/callback')
def callback():
    # Extract 'code' parameter from the query string
    code = request.args.get('code')

    if code:
        # Call the function to exchange the code for an access token
        access_token = get_access_token(
            client_id, code, redirect_uri, code_verifier)
        if access_token is None:
            return "Error: Unable to retrieve access token", 500

        return get_user_top_tracks(access_token)
    else:
        return "Error: No code found in the query parameters", 400

# Step X. User has accepted authorisation request, now to exchange the auth code for an access token


def get_access_token(client_id, auth_code, redirect_uri, code_verifier):
    url = "https://accounts.spotify.com/api/token"
    payload = {
        'client_id': client_id,
        'grant_type': 'authorization_code',
        'code': auth_code,
        'redirect_uri': redirect_uri,
        'code_verifier': code_verifier
    }

    # Make the POST request to Spotify's token endpoint
    response = requests.post(url, data=payload, headers={
        'Content-Type': 'application/x-www-form-urlencoded'
    })

    # Check response
    if response.status_code == 200:
        # Success, parse JSON
        token_data = response.json()
        return token_data.get('access_token')  # Return the access token
    else:
        print("Error:", response.status_code, response.text)
        return None


def get_user_top_tracks(access_token):

    # Spotify endpoint for fetching the user's top tracks
    url = "https://api.spotify.com/v1/me/top/tracks"

    # Set up the parameters for the request
    params = {
        'time_range': 'short_term',  # Time range: short_term (last 4 weeks)
        'limit': 25  # Limit the results to 25 tracks
    }

    # Make the GET request to Spotify's API, passing the authorization token in the header
    response = requests.get(url, headers={
        'Authorization': f'Bearer {access_token}'
    }, params=params)

    # Check if the response was successful
    if response.status_code == 200:
        # Parse and return the JSON response
        top_tracks_data = response.json()
        return top_tracks_data['items']  # Return the list of tracks
    else:
        print("Error fetching top tracks:",
              response.status_code, response.text)
        return None


if __name__ == '__main__':
    app.run(port=8888, debug=True)
