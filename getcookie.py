import requests
from bs4 import BeautifulSoup

def authenticate_and_save_cookies(username, password, cookie_file="cookies.txt"):
    session = requests.Session()

    # Get login page to retrieve CSRF token
    login_url = "http://127.0.0.1:8000/admin/login/"
    response = session.get(login_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    csrf_token = soup.find('input', {'name': 'csrfmiddlewaretoken'})['value']

    # Login - follow redirects to avoid the /accounts/profile/ issue
    login_data = {
        'username': username,
        'password': password,
        'csrfmiddlewaretoken': csrf_token,
        'next': '/admin/'  # Redirect to admin page after login
    }
    login_response = session.post(login_url, data=login_data, headers={'Referer': login_url}, allow_redirects=True)

    # Check if login was successful by checking for a redirect to admin or similar
    if login_response.status_code in [200, 302] and ('admin' in login_response.url or login_response.status_code == 200):
        # Save cookies to file in a format that curl can use
        with open(cookie_file, 'w') as f:
            for cookie in session.cookies:
                # Format: domain flag path flag secure expiration name value
                f.write(f"127.0.0.1\tFALSE\t/\tFALSE\t0\t{cookie.name}\t{cookie.value}\n")

        print(f"Authentication successful. Cookies saved to {cookie_file}")
        return session
    else:
        print(f"Authentication failed. Status code: {login_response.status_code}, URL: {login_response.url}")
        return None

if __name__ == "__main__":
    username = input("Enter your Django username: ")
    password = input("Enter your Django password: ")

    authenticate_and_save_cookies(username, password)