#!/usr/bin/env python3
"""
YouTube OAuth2 Token Generator
Generates Refresh Token needed for Smart Shorts automation
"""

import os
import sys
import json
import webbrowser
import http.server
import socketserver
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

def get_youtube_refresh_token(client_id, client_secret):
    """Interactive OAuth2 flow to get YouTube refresh token"""
    
    print("\n" + "="*60)
    print("🎬 YouTube Refresh Token Generator")
    print("="*60 + "\n")
    
    # Step 1: Generate authorization URL
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}"
        f"&redirect_uri=http://localhost:8080/callback"
        f"&response_type=code"
        f"&scope=https://www.googleapis.com/auth/youtube"
        f"&access_type=offline"
        f"&prompt=consent"
    )
    
    print("📱 Opening browser for authorization...\n")
    print(f"Authorization URL:\n{auth_url}\n")
    
    # Try to open browser
    try:
        webbrowser.open(auth_url)
    except:
        print("⚠️  Could not open browser automatically")
        print(f"Please visit this URL manually:\n{auth_url}\n")
    
    # Step 2: Start local server to capture callback
    captured_code = None
    
    class CallbackHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            nonlocal captured_code
            
            query = urlparse(self.path).query
            params = parse_qs(query)
            
            if 'code' in params:
                captured_code = params['code'][0]
                
                # Send success response
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                
                html = """
                <html>
                <head><title>Success!</title></head>
                <body style="font-family: Arial; text-align: center; margin-top: 50px;">
                    <h1>✅ Authorization Successful!</h1>
                    <p>You can close this window and return to the terminal.</p>
                </body>
                </html>
                """
                
                self.wfile.write(html.encode())
            else:
                self.send_response(400)
                self.end_headers()
        
        def log_message(self, format, *args):
            pass
    
    # Start server
    print("⏳ Waiting for authorization callback...")
    print("   (Listening on http://localhost:8080/callback)\n")
    
    try:
        with socketserver.TCPServer(("", 8080), CallbackHandler) as httpd:
            # Wait for callback (timeout after 2 minutes)
            import threading
            
            timeout = 120
            server_thread = threading.Thread(target=httpd.serve_forever)
            server_thread.daemon = True
            server_thread.start()
            
            # Wait for code
            import time
            start = time.time()
            while captured_code is None and time.time() - start < timeout:
                time.sleep(0.1)
            
            httpd.shutdown()
    
    except OSError as e:
        print(f"❌ Could not start server: {e}")
        print("\nAlternative: Run with --manual and paste authorization code\n")
        return None
    
    if not captured_code:
        print("❌ Authorization timeout")
        return None
    
    print(f"✅ Got authorization code\n")
    
    # Step 3: Exchange code for tokens
    print("🔄 Exchanging code for tokens...\n")
    
    try:
        import requests
        
        token_url = "https://oauth2.googleapis.com/token"
        
        data = {
            'code': captured_code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': 'http://localhost:8080/callback',
            'grant_type': 'authorization_code'
        }
        
        response = requests.post(token_url, data=data)
        
        if response.status_code != 200:
            print(f"❌ Token exchange failed: {response.text}\n")
            return None
        
        tokens = response.json()
        refresh_token = tokens.get('refresh_token')
        
        if not refresh_token:
            print("❌ No refresh token in response\n")
            print("Make sure you selected 'offline access'")
            return None
        
        # Step 4: Display results
        print("="*60)
        print("✅ SUCCESS! Token Generated")
        print("="*60 + "\n")
        
        print("📋 Save these values to GitHub Secrets:\n")
        print(f"Name:  YT_REFRESH_TOKEN_3")
        print(f"Value: {refresh_token}\n")
        
        print(f"Name:  YT_CLIENT_ID_3")
        print(f"Value: {client_id}\n")
        
        print(f"Name:  YT_CLIENT_SECRET_3")
        print(f"Value: {client_secret}\n")
        
        # Option to save to .env
        print("\n💾 Save to file? (y/n): ", end='')
        if input().lower() == 'y':
            env_content = f"""# YouTube API Credentials
YT_CLIENT_ID_3={client_id}
YT_CLIENT_SECRET_3={client_secret}
YT_REFRESH_TOKEN_3={refresh_token}
YT_CHANNEL_ID=your_channel_id_here
"""
            
            with open('.env', 'w') as f:
                f.write(env_content)
            
            print("✅ Saved to .env\n")
        
        return refresh_token
        
    except Exception as e:
        print(f"❌ Error: {e}\n")
        return None


def main():
    print("\n🚀 YouTube Refresh Token Setup\n")
    
    # Get credentials
    print("You need Google Cloud Console credentials first.")
    print("If you don't have them, get them here:")
    print("https://console.cloud.google.com/\n")
    
    client_id = input("Enter Client ID: ").strip()
    client_secret = input("Enter Client Secret: ").strip()
    
    if not client_id or not client_secret:
        print("\n❌ Invalid credentials\n")
        return
    
    # Generate token
    refresh_token = get_youtube_refresh_token(client_id, client_secret)
    
    if refresh_token:
        print("📚 Next Steps:")
        print("1. Add YT_REFRESH_TOKEN_3 to GitHub Secrets")
        print("2. Add YT_CHANNEL_ID to GitHub Secrets")
        print("3. Push code to trigger workflow")
        print("\n✅ Done!\n")
    else:
        print("❌ Failed to generate token\n")


if __name__ == '__main__':
    main()
