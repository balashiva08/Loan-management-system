
from getpass import getpass
from werkzeug.security import generate_password_hash

username = input("Enter your login username: ").strip()
password = getpass("Enter your login password: ")
confirm_password = getpass("Confirm your password: ")

if not username or not password:
    print("Username and password cannot be empty.")
elif password != confirm_password:
    print("Passwords do not match.")
else:
    password_hash = generate_password_hash(password)

    with open("user.txt", "w") as file:
        file.write(username + "\n")
        file.write(password_hash)

    print("Login user created successfully!")
