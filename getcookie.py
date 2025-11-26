import requests
from bs4 import BeautifulSoup

def authenticate_and_save_cookies(username, password, cookie_file="cookies.txt"):
    session = requests.Session()

    # Get login page to retrieve CSRF token
    login_url = "http://127.0.0.1:8000/admin/login/"
    response = session.get(login_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    csrf_token = soup.find('input', {'name': 'csrfmiddlewaretoken'})['value']

    # Login
    login_data = {
        'username': username,
        'password': password,
        'csrfmiddlewaretoken': csrf_token
    }
    login_response = session.post(login_url, data=login_data, headers={'Referer': login_url})

    if login_response.status_code == 200:
        # Save cookies to file
        with open(cookie_file, 'w') as f:
            for cookie in session.cookies:
                f.write(f"{cookie.name}={cookie.value}\n")

        # Also save in requests format using pickle if needed
        session.cookies.save(ignore_discard=True, filename=cookie_file + ".pkl")

        print(f"Authentication successful. Cookies saved to {cookie_file}")
        return session
    else:
        print(f"Authentication failed. Status code: {login_response.status_code}")
        return None

if __name__ == "__main__":
    username = input("Enter your Django username: ")
    password = input("Enter your Django password: ")

    authenticate_and_save_cookies(username, password)