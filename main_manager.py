from src.youtube_client import YouTubeClient
from src.manager import Manager

def main():
    print("🧠 Running Manager Analysis...")
    yt = YouTubeClient()
    stats = yt.get_analytics()
    
    manager = Manager()
    new_state = manager.analyze_and_adjust(stats)
    
    print(f"New Strategy: {new_state['preferred_template_id']}")
    print(f"Risk Level: {new_state['risk_level']}")

if __name__ == "__main__":
    main()
