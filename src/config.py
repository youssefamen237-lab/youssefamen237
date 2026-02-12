import os
import json

class Config:
    # YouTube Keys
    YT_CLIENT_ID = os.getenv("YT_CLIENT_ID_3")
    YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET_3")
    YT_REFRESH_TOKEN = os.getenv("YT_REFRESH_TOKEN_3")
    CHANNEL_ID = os.getenv("YT_CHANNEL_ID")
    
    # AI Keys
    OPENAI_KEY = os.getenv("OPENAI_API_KEY")
    GEMINI_KEY = os.getenv("GEMINI_API_KEY") # تأكد أن هذا الاسم مطابق لـ GitHub Secrets
    
    # Media APIs
    PEXELS_KEY = os.getenv("PEXELS_API_KEY")
    
    # Paths
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    ASSETS_DIR = os.path.join(BASE_DIR, 'assets')
    OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
    
    # Settings
    FONT_PATH = os.path.join(ASSETS_DIR, 'fonts', 'Arimo-Bold.ttf')
    
    @staticmethod
    def ensure_dirs():
        os.makedirs(Config.DATA_DIR, exist_ok=True)
        os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
        os.makedirs(os.path.join(Config.ASSETS_DIR, 'backgrounds'), exist_ok=True)
        os.makedirs(os.path.join(Config.ASSETS_DIR, 'fonts'), exist_ok=True)
        
        files = ['content_registry.json', 'performance_db.json', 'upload_queue.json', 'ab_tests.json']
        for f in files:
            path = os.path.join(Config.DATA_DIR, f)
            if not os.path.exists(path):
                with open(path, 'w') as json_file:
                    json.dump([], json_file)

Config.ensure_dirs()
