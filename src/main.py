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
auth_url += "?" + urllib.parse.urlencode(params)

# Using authorisation code to then obtain an access token for intrusive API calls (user-specific)


def generate_authorisation_token(auth_code):
    # Step X. User has accepted authorisation request, now to exchange the auth code for an access token
    # Requesting an Access Token
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

# Credentials used to obtain access for non-intrusive API calls (i.e. calls not related to user-specific data)


def generate_client_credentials():
    auth_value = base64.b64encode(
        f'{client_id}:{client_secret}'.encode('utf-8')).decode('utf-8')

    url = 'https://accounts.spotify.com/api/token'
    headers = {
        "Authorization": f"Basic {auth_value}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        'grant_type': 'client_credentials'
    }

    # Make the POST request
    response = requests.post(url, headers=headers, data=data)

    if response.status_code == 200:
        token_data = response.json()
        return token_data.get('access_token')
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return None


app = Flask(__name__)

# Route to redirect user to Spotify's authorisation page


@app.route('/')
def redirect_to_spotify():
    return redirect(auth_url)
    # return recommendations_from_mood(generate_client_credentials())


@app.route('/callback')
def callback():
    print(app.url_map)

    # Extract 'code' parameter from the query string
    auth_code = request.args.get('code')
    if not auth_code:
        return "Error: No code found in the query parameters", 400

    # return get_user_top_tracks(generate_authorisation_token(auth_code))
    return recommendations_from_mood(generate_client_credentials())


def get_user_top_tracks(access_token):

    url = "https://api.spotify.com/v1/me/top/tracks"
    params = {
        'time_range': 'short_term',
        'limit': 25 # TODO: Base this value on car journey length
    }

    response = requests.get(url, headers={
        'Authorization': f'Bearer {access_token}'
    }, params=params)

    if response.status_code == 200:
        top_tracks_data = response.json()
        return top_tracks_data['items']
    else:
        print("Error fetching top tracks:",
              response.status_code, response.text)
        return None


def recommendations_from_mood(access_token):
    import requests


def get_similar_tracks(artist, track, api_key, limit=5):
    url = "https://ws.audioscrobbler.com/2.0/"

    params = {
        'method': 'track.getsimilar',
        'artist': artist,
        'track': track,
        'api_key': api_key,
        'limit': 5,
        'format': 'json'
    }

    response = requests.get(url, params=params)

    # Check if the request was successful
    if response.status_code == 200:
        data = response.json()
        if 'similartracks' in data:
            similar_tracks = data['similartracks']['track']
            return similar_tracks
        else:
            print("No similar tracks found or error in response data.")
            return None
    else:
        print(f"Error {response.status_code}: {response.text}")
        return None


@app.route('/test')
def test_route():
    return "Test route works!"


if __name__ == '__main__':
    app.run(port=8888, debug=True)
