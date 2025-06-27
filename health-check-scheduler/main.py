import requests
import json

def check_health(url):
    """
    Send a GET request to the specified URL and return the response
    """
    try:
        print(f"Sending GET request to: {url}")
        response = requests.get(url)
        
        # Print status code
        print(f"Status Code: {response.status_code}")
        
        # Print response headers
        print(f"Response Headers: {dict(response.headers)}")
        
        # Try to parse JSON response, fallback to text if not JSON
        try:
            response_data = response.json()
            print("Response Body (JSON):")
            print(json.dumps(response_data, indent=2))
        except ValueError:
            print("Response Body (Text):")
            print(response.text)
            
        return response
        
    except requests.exceptions.RequestException as e:
        print(f"Error occurred: {e}")
        return None

if __name__ == "__main__":
    # Example endpoint - you can change this to any URL you want to test
    endpoint = "https://northstar-system-final-production.up.railway.app/health"
    
    # You can also uncomment the line below to input a custom URL
    # endpoint = input("Enter the URL to send GET request to: ")
    
    check_health(endpoint)
