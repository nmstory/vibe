from dotenv import load_dotenv
from flask import Flask, redirect, request, render_template, jsonify, session
import secrets
import string
import hashlib
import urllib.parse
import os
import base64
import requests
import googlemaps

load_dotenv()

spotify_client_id = os.getenv("SPOTIFY_CLIENT_ID")
spotify_client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
last_fm_api_key = os.getenv("LAST_FM_API_KEY")
last_fm_secret = os.getenv("LAST_FM_SECRET")
google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")

# init google maps API
gmaps = googlemaps.Client(key=google_maps_api_key)

def generate_random_string(length):
    possible_chars = string.ascii_letters + string.digits  # A-Z, a-z, 0-9
    return ''.join(secrets.choice(possible_chars) for _ in range(length))


# Generating Spotify authentication url
code_verifier = generate_random_string(64)
hash_sha256 = hashlib.sha256(code_verifier.encode('utf-8')).digest()
auth_base64 = base64.urlsafe_b64encode(hash_sha256).decode('utf-8').rstrip('=')

redirect_uri = "http://localhost:8888/callback"
auth_url = "https://accounts.spotify.com/authorize"

scope = "user-read-private user-read-email user-top-read playlist-modify-public playlist-modify-private"
params = {
    'response_type': 'code',
    'client_id': spotify_client_id,
    'scope': scope,
    'code_challenge_method': 'S256',
    'code_challenge': auth_base64,
    'redirect_uri': redirect_uri,
}
auth_url += "?" + urllib.parse.urlencode(params)

# Using authorisation code to then obtain an access token for intrusive API calls (user-specific)
def generate_authorisation_token():
    
    spotify_auth_code = session.get('spotify_auth_code')
    if not spotify_auth_code:
        return "Error: No code for spotify found", 400
    
    # Requesting an Access Token
    url = "https://accounts.spotify.com/api/token"
    payload = {
        'client_id': spotify_client_id,
        'grant_type': 'authorization_code',
        'code': spotify_auth_code,
        'redirect_uri': redirect_uri,
        'code_verifier': code_verifier
    }

    auth = (spotify_client_id, spotify_client_secret)
    response = requests.post(url, data=payload, headers={'Content-Type': 'application/x-www-form-urlencoded'}, auth=auth)

    # Check response
    if response.status_code == 200:
        token_data = response.json()
        access_token = token_data.get('access_token')
        session['spotify_access_token'] = access_token
        return access_token
    else:
        print("Error:", response.status_code, response.text)
        return None

# Credentials used to obtain access for non-intrusive API calls (i.e. calls not related to user-specific data)
def generate_client_credentials():
    auth_value = base64.b64encode(
        f'{spotify_client_id}:{spotify_client_secret}'.encode('utf-8')).decode('utf-8')

    url = 'https://accounts.spotify.com/api/token'
    headers = {
        "Authorization": f"Basic {auth_value}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        'grant_type': 'client_credentials'
    }

    response = requests.post(url, headers=headers, data=data)

    # Check response
    if response.status_code == 200:
        token_data = response.json()
        return token_data.get('access_token')
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return None

# Calculates travel time (in minutes by default)
def calculate_travel_time(origin, destination):
    try:
        directions = gmaps.directions(
            origin,
            destination,
            mode="driving",
            departure_time="now"
        )
        
        if directions:
            return directions[0]['legs'][0]['duration']['text']
        else:
            return jsonify({"success": False, "message": "Could not find directions."})
    
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

def get_track_spotify_uri(track_name, track_artist):
    url = "https://api.spotify.com/v1/search"
    query = f"track:{track_name} artist:{track_artist}"
    params = {
        'q': query,
        'type': 'track',
        'limit': 1 # Return one result
    }

    response = requests.get(url, headers={
        'Authorization': f'Bearer {generate_client_credentials()}'
    }, params=params)

    # Check response
    if response.status_code == 200:
        search_results = response.json()
        tracks = search_results.get('tracks', {}).get('items', [])
        
        if tracks:
            track = tracks[0]
            return track['uri']
        else:
            print("Failed to obtain URI for a track")
            return None
    else:
        print("Error searching for track:", response.status_code, response.text)
        return None
    
def get_user_top_tracks():
    access_token = session.get("spotify_access_token")

    url = "https://api.spotify.com/v1/me/top/tracks"
    params = {
        'time_range': 'short_term',
        'limit': 25 # TODO: Base this value on car journey length
    }

    response = requests.get(url, headers={
        'Authorization': f'Bearer {access_token}'
    }, params=params)

    # Check response
    if response.status_code == 200:
        top_tracks_data = response.json()
        return top_tracks_data['items']
    else:
        print("Error fetching top tracks:",
              response.status_code, response.text)
        return None

def recommendations_from_mood(mood):
    url = f"http://ws.audioscrobbler.com/2.0/?method=tag.getTopTracks&tag={mood}&api_key={last_fm_api_key}&format=json&limit=10"

    response = requests.get(url)
    data = response.json()

    tracks_with_uri = []
    if 'tracks' in data:
        for track in data['tracks']['track']:
            # Fetching Spotify URL after using Last FM API
            uri = get_track_spotify_uri(track['name'], track['artist']['name'])
            if uri:
                tracks_with_uri.append(uri)
        
        return tracks_with_uri
    else:
        print(f"No tracks found for mood: {mood}")
        return None

def get_similar_tracks(track, artist, limit=5):
    url = "https://ws.audioscrobbler.com/2.0/"

    params = {
        'method': 'track.getsimilar',
        'artist': artist,
        'track': track,
        'api_key': last_fm_api_key,
        'limit': limit,
        'format': 'json'
    }

    response = requests.get(url, params=params)

    if response.status_code == 200:
        data = response.json()
        if 'similartracks' in data:
            similar_tracks = data['similartracks']['track']

            uris_of_similar_tracks = []
            for track in similar_tracks:
                # Fetching Spotify URI after using Last FM API
                uri = get_track_spotify_uri(track['name'], track['artist']['name'])
                if uri:
                    uris_of_similar_tracks.append(uri)

            return uris_of_similar_tracks
        else:
            print("No similar tracks found or error in response data.")
            return None
    else:
        print(f"Error {response.status_code}: {response.text}")
        return None


def create_playlist(destination):
    access_token = session.get("spotify_access_token")
    url = "https://api.spotify.com/v1/me/playlists"
    
    headers = {
        'Authorization': f"Bearer {access_token}",
        'Content-Type': 'application/json'
    }
    
    data = {
        "name": f"{destination} Playlist!",
        "description": f"Your Roadtrip Playlist for {destination}!",
        "public": False
    }
    
    response = requests.post(url, headers=headers, json=data)
    
    # Check response
    if response.status_code == 201:
        playlist_data = response.json()
        return playlist_data['id']
    else:
        print(f"Error creating playlist: {response.status_code} - {response.text}")
        return None
    
def add_tracks_to_playlist(playlist_id, track_list):
    access_token = session.get("spotify_access_token")
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    
    headers = {
        'Authorization': f"Bearer {access_token}",
    }
    
    # Spotify has a limit of 100 new tracks that can be added at once to a playlist
    track_uris = track_list[:100] 
    del track_list[:100]

    data = {
        "uris": track_uris
    }

    response = requests.post(url, headers=headers, json=data)
    
    # Check response
    if response.status_code == 201:
        # If there are more tracks remaining to be added, repeat
        if track_list:
            add_tracks_to_playlist(playlist_id, track_list)
        return True
    else:
        print(f"Error adding tracks: {response.status_code} - {response.text}")

def get_playlist_url(playlist_id):
    access_token = session.get("spotify_access_token")
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}"
    
    headers = {
        'Authorization': f"Bearer {access_token}",
    }

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        playlist_data = response.json()
        playlist_url = playlist_data.get('external_urls', {}).get('spotify')
        if playlist_url:
            return playlist_url
        else:
            print("Error: Playlist URL not found.")
            return None
    else:
        print(f"Error: Unable to fetch playlist details. Status code {response.status_code} with error {response.text}")
        return None

# Init Flask
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# Route to redirect user to Spotify's authorisation page
@app.route('/')
def redirect_to_spotify():
    return redirect(auth_url)
    # return recommendations_from_mood(generate_client_credentials())

@app.route('/callback')
def callback():
    spotify_auth_code = request.args.get('code')

    if not spotify_auth_code:
        return "Error: No code for spotify found in the query parameters", 400
    else:
        session['spotify_auth_code'] = spotify_auth_code

    return render_template('index.html')

@app.route('/generate_playlist', methods=['POST'])
def generate_playlist():
    # todo: make use of travel time value
    """
    response = calculate_travel_time(request.form['origin'], request.form['destination'])

    if isinstance(response, dict) and response.get("success") == False:
        return jsonify(response)
    """
    generate_authorisation_token()

    track_list = []
    top_tracks = get_user_top_tracks()
    
    if top_tracks:
        for track in top_tracks:            
            track_list.append(track['uri'])
            track_list.extend(get_similar_tracks(track['name'], track['artists'][0]['name']))

    track_list.extend(recommendations_from_mood(request.form['mood']))
    
    # Create playlist
    playlist_id = create_playlist(request.form['destination'])
    if add_tracks_to_playlist(playlist_id, track_list) :
        playlist_url = get_playlist_url(playlist_id)
        return jsonify(playlist_url)
    
if __name__ == '__main__':
    app.run(port=8888, debug=True)