import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/drive']

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    client_secret_path = os.path.join(base_dir, 'config', 'client_secret.json')
    token_path = os.path.join(base_dir, 'config', 'google_drive_token.json')

    if not os.path.exists(client_secret_path):
        print("❌ CLIENT SECRET NOT FOUND!")
        print(f"Please place your downloaded Google OAuth Client Secret JSON key at:\n  👉 {client_secret_path}")
        print("\nHow to get it:")
        print("1. Go to Google Cloud Console > APIs & Services > Credentials.")
        print("2. Click 'Create Credentials' > 'OAuth client ID'.")
        print("3. Set Application Type to 'Desktop app' and Name it.")
        print("4. Click 'Create' and then click 'Download JSON' for the newly created credentials.")
        print("5. Rename the downloaded file to 'client_secret.json' and place it in the config/ folder.")
        return

    print("🔑 Initiating Google Drive login...")
    print("A browser window will open shortly to ask for consent to access Google Drive.")
    try:
        flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
        creds = flow.run_local_server(port=0)

        # Save credentials to google_drive_token.json
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, 'w') as token_file:
            token_file.write(creds.to_json())

        print(f"\n✅ SUCCESS: Successfully logged in and authorized Google Drive!")
        print(f"Saved token to: {token_path}")
    except Exception as e:
        print(f"\n❌ Error during authorization: {e}")

if __name__ == '__main__':
    main()
