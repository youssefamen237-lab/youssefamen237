import os
import sys
import time
from datetime import datetime

# Import all components
from generators.question_generator import generate_unique_question, generate_multiple_questions
from video_engine.video_generator import generate_video_assets
from voice_engine.voice_generator import generate_voice_speech
from seo_engine.seo_optimizer import optimize_title, optimize_description, generate_tags
from publishing.youtube_publisher import publish_shorts_video, publish_long_video
from analytics.analytics_engine import load_video_data, calculate_performance_metrics, generate_insights
from optimization.optimization_engine import analyze_current_strategy, suggest_optimizations, recommend_next_steps
from database.db import init_db

# Main Controller for the Self-Governing AI YouTube Channel

class YouTubeChannelController:
    def __init__(self):
        self.init_system()
        
    def init_system(self):
        """
        Initialize the entire system
        """
        print("Initializing Self-Governing AI YouTube Channel System...")
        
        # Initialize database
        init_db()
        print("✓ Database initialized")
        
        # Create required directories
        directories = ['videos', 'voices', 'thumbnails', 'data']
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
        print("✓ Required directories created")
        
        print("System initialization complete!")
        
    def generate_shorts_content(self, count=1):
        """
        Generate Shorts content
        
        Args:
            count (int): Number of shorts to generate
        """
        print(f"\n=== Generating {count} Shorts ===")
        
        for i in range(count):
            print(f"\n--- Generating Short {i+1} ---")
            
            # Generate question
            question = generate_unique_question()
            print(f"Question: {question}")
            
            # Generate answer (simplified for demo)
            answer = f"The answer to '{question}' is very interesting!"
            print(f"Answer: {answer}")
            
            # Optimize SEO
            title = optimize_title(question)
            description = optimize_description(question)
            tags = generate_tags(question)
            print(f"Title: {title}")
            print(f"Tags: {tags}")
            
            # Generate video assets
            assets = generate_video_assets(question, answer)
            print(f"Video assets generated: {assets}")
            
            # Generate voice
            voice_file = generate_voice_speech(answer, f"voice_{i+1}.mp3")
            print(f"Voice generated: {voice_file}")
            
            # Mock publish (in real system, this would actually publish)
            publish_result = publish_shorts_video(title, description, "thumbnail.jpg", "video.mp4")
            print(f"Publish result: {publish_result}")
            
            print(f"Short {i+1} completed successfully!")
            
            # Small delay between videos
            time.sleep(1)
        
        print(f"\n=== All {count} Shorts generated and processed ===")
        
    def generate_long_content(self, count=1):
        """
        Generate Long-form content
        
        Args:
            count (int): Number of long videos to generate
        """
        print(f"\n=== Generating {count} Long Videos ===")
        
        for i in range(count):
            print(f"\n--- Generating Long Video {i+1} ---")
            
            # Generate multiple questions
            questions = generate_multiple_questions(5)
            print(f"Questions: {questions}")
            
            # Generate answers (simplified for demo)
            answers = [f"The answer to '{q}' is quite interesting!" for q in questions]
            
            # Combine into QA pairs
            qa_pairs = [{'question': q, 'answer': a} for q, a in zip(questions, answers)]
            
            # Optimize SEO
            title = f"Top 5 Facts About {questions[0][:20]}..."
            description = f"Learn interesting facts about {questions[0]} and other related topics in this comprehensive video."
            tags = generate_tags(questions[0])
            print(f"Title: {title}")
            print(f"Tags: {tags}")
            
            # Generate long video compilation
            compilation_file = generate_video_assets(questions[0], answers[0])['compilation']
            print(f"Compilation generated: {compilation_file}")
            
            # Generate voice for narration
            narration_text = "Welcome to today's educational video where we explore fascinating facts about various topics."
            voice_file = generate_voice_speech(narration_text, f"narration_{i+1}.mp3")
            print(f"Narration voice generated: {voice_file}")
            
            # Mock publish (in real system, this would actually publish)
            publish_result = publish_long_video(title, description, "thumbnail.jpg", "video.mp4")
            print(f"Publish result: {publish_result}")
            
            print(f"Long Video {i+1} completed successfully!")
            
            # Small delay between videos
            time.sleep(1)
        
        print(f"\n=== All {count} Long Videos generated and processed ===")
        
    def run_daily_cycle(self):
        """
        Run a complete daily cycle (4 Shorts + 1 Long)
        """
        print("\n=== Starting Daily Content Cycle ===")
        
        # Generate 4 Shorts
        self.generate_shorts_content(4)
        
        # Generate 1 Long video
        self.generate_long_content(1)
        
        print("\n=== Daily Content Cycle Complete ===")
        
    def run_weekly_analysis(self):
        """
        Run weekly performance analysis and optimization
        """
        print("\n=== Running Weekly Analysis ===")
        
        # Load video data
        data = load_video_data(20)
        print(f"Loaded {len(data)} videos for analysis")
        
        # Calculate metrics
        metrics = calculate_performance_metrics()
        print(f"Performance Metrics: {metrics}")
        
        # Generate insights
        insights = generate_insights()
        print(f"Actionable Insights: {insights['insights'][:3]}...")
        
        # Analyze strategy
        strategy_analysis = analyze_current_strategy()
        print(f"Strategy Priorities: {strategy_analysis['priorities']}")
        
        # Suggest optimizations
        optimizations = suggest_optimizations()
        print(f"Optimization Suggestions: {list(optimizations['suggestions'].keys())}")
        
        # Recommend next steps
        recommendations = recommend_next_steps()
        print(f"Next Steps: {recommendations['content_strategy']}")
        
        print("\n=== Weekly Analysis Complete ===")
        
    def run_autonomous_cycle(self):
        """
        Run the complete autonomous cycle
        """
        print("\n🚀 Starting Autonomous YouTube Channel System 🚀")
        
        while True:
            try:
                # Run daily cycle
                self.run_daily_cycle()
                
                # Run weekly analysis
                self.run_weekly_analysis()
                
                # Wait for next cycle (in real system, this would be scheduled)
                print("\n⏳ Waiting for next cycle... (30 seconds for demo)")
                time.sleep(30)
                
            except KeyboardInterrupt:
                print("\n🛑 System shutdown requested")
                break
            except Exception as e:
                print(f"\n❌ Error in autonomous cycle: {e}")
                print("Continuing with next cycle...")
                time.sleep(10)
        
        print("\n🏁 Autonomous YouTube Channel System Shutdown Complete")

# Main execution function
if __name__ == '__main__':
    # Create controller instance
    controller = YouTubeChannelController()
    
    print("Self-Governing AI YouTube Channel System v1.0")
    print("=============================================")
    
    # Run a quick demo
    print("\n🧪 Running Quick Demo...")
    
    # Generate a few shorts for demo
    controller.generate_shorts_content(2)
    
    # Generate a long video for demo
    controller.generate_long_content(1)
    
    print("\n✅ Demo completed successfully!")
    print("\nTo run the full autonomous system, call: controller.run_autonomous_cycle()")