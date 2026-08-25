import json
import os
import bcrypt
import getpass

USER_FILE = "users.json"

def load_users():
    if os.path.exists(USER_FILE):
        with open(USER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4)

def main():
    print("--- LocaNoto Benutzerverwaltung ---")
    users = load_users()
    
    username = input("Neuer Benutzername: ").strip().lower()
    if username in users:
        print(f"Benutzer '{username}' existiert bereits!")
        return
        
    # getpass sorgt dafür, dass die Eingabe im Terminal unsichtbar bleibt (wie bei Linux-Logins)
    password = getpass.getpass("Passwort: ")
    
    # 1. Salt generieren (Zufallswert)
    salt = bcrypt.gensalt()
    # 2. Passwort mit dem Salt hashen
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
    
    # Den Hash als String in der JSON speichern
    users[username] = hashed_password.decode('utf-8')
    save_users(users)
    
    print(f"✅ Benutzer '{username}' erfolgreich und sicher angelegt!")

if __name__ == "__main__":
    main()