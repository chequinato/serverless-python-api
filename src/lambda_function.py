
from src.secrets import get_api_key
from src.api_client import fetch_live_rates
from src.api_client import fetch_historical_rates
from src.api_client import APIError, APIRateLimitError, APIAuthError
from src.processor import

def lambda_handler(event, context):

    # Passo 1
    try:
       api_key =  get_api_key()
    except RuntimeError:
        return ...
    except EnvironmentError:
        return ...

     # Passo 2
    try:
        live_rates = fetch_live_rates(api_key)
    except APIAuthError as e:
        return _response(401, {"error": str(e)})
    except APIRateLimitError as e:
        return _response(429, {"error": str(e)})
    except APIError as e:
        return _response(502, {"error": str(e)})

    # Passo 3
    try:
        historical_rates = fetch_historical_rates(api_key)
    except APIAuthError as e:
        return _response(401, {"error": str(e)})
    except APIRateLimitError as e:
        return _response(429, {"error": str(e)})
    except APIError as e:
        return _response(502, {"error": str(e)})

    # Passo 4
    try:


    except:

    # Passo 5
     try:

    except: