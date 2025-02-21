# vibe

Welcome to Project Vibe: your go-to Spotify playlist generator before heading out on a drive!

**Vibe will only ask you to input:**

1. Your starting location
2. Your desired destination
3. Your current mood

**And from this, will curate a unique playlist for your journey based on factors such as:**

* The length of your journey, and how that matches to the way you feel (_daunted at a long drive?_).
* The weather in both your departure and arrival destinations (_arriving to a destination with better or worse weather?_).
* The time of day (_is the sun about to set as you drive?_).
* Music that's popular in the local area of your destination, that also matches your taste.
* Your current heavy rotation of music.

## Inspiration for the Name

Whilst the aim of this project is to accurately curate a Spotify playlist to set the perfect _vibe_ for your ride, I'm also currently learning Portuguese, and this is also an acronym for the slightly more Brazilian phrase **_v_**_amos_ **_i_**_ntensificar o_ **_b_**_om_ **_e_**_squema_, which roughly translate as slang to English as _let's get this vibe right_.

# Prerequisites

## Frameworks:
- Python (version: 3.13.2)
- Flask (version: 3.1.0)
- python-dotenv (version: 1.0.1)
- requests (version: 2.32.3)
- googlemaps (version: 4.10.0)

_Installable with:_
```
pip install python-dotenv requests flask googlemaps
```

## API Keys and .env
The implementation of vibe makes use of three API's: [Spotify](https://developer.spotify.com/), [Google Cloud](https://cloud.google.com/apis) and [Last FM](https://www.last.fm/api).

For you to get vibe working locally, you'll need to personally generate your own API keys, then place them into a .env at the root of the project:
_/.env_
```
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
LAST_FM_API_KEY=
LAST_FM_SECRET=
GOOGLE_MAPS_API_KEY=
FLASK_SECRET_KEY=
```

## Spotify Authentication Flow

To increase security within the desired environment (eventually potentially a web app), the [Spotify authentication flow](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow) uses an authorisation code with PKCE - in the event that the runtime environment may provide an opportunity for the authorisation code to be intercepted.

Follows this flow:

1. Code Challenge generation from a Code Verifier
2. Request authorisation from the user and retrieve the authorisation code
3. Request an access token from the authorisation code
4. Use the access token to make API calls
