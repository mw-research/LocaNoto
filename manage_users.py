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
    users = load_users()
    print("\n=== LocaNoto Benutzerverwaltung ===")
    print("Derzeitige Nutzer im System:", ", ".join(users.keys()))
    print("-----------------------------------")
    print("1: Passwort ändern")
    print("2: Benutzer löschen")
    print("3: Beenden")
    
    auswahl = input("\nWas möchtest du tun? (1/2/3): ").strip()
    
    if auswahl == "1":
        username = input("Benutzername: ").strip().lower()
        if username not in users:
            print(f"❌ Fehler: Benutzer '{username}' existiert nicht.")
            return
        new_password = getpass.getpass("Neues Passwort: ")
        salt = bcrypt.gensalt()
        users[username] = bcrypt.hashpw(new_password.encode('utf-8'), salt).decode('utf-8')
        save_users(users)
        print(f"✅ Passwort für '{username}' wurde erfolgreich aktualisiert!")
        
    elif auswahl == "2":
        username = input("Welcher Benutzer soll gelöscht werden?: ").strip().lower()
        if username not in users:
            print(f"❌ Fehler: Benutzer '{username}' existiert nicht.")
            return
        if username == "markus":
            print("⚠️ Warnung: Du bist im Begriff, deinen eigenen Admin-Account zu löschen!")
            
        bestaetigung = input(f"Bist du sicher, dass du '{username}' unwiderruflich löschen willst? (j/n): ").strip().lower()
        if bestaetigung == 'j':
            del users[username]
            save_users(users)
            print(f"🗑️ Benutzer '{username}' wurde erfolgreich gelöscht! Der Login ist ab sofort gesperrt.")
        else:
            print("Abbruch. Es wurde nichts gelöscht.")
            
    else:
        print("Tschüss!")

if __name__ == "__main__":
    main()
    