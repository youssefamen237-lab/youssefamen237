import os
import time
import logging
import random
from datetime import datetime, timedelta

class FallbackSystem:
    def __init__(self):
        self.setup_logger()
        self.failures = {}
        self.last_failure_time = {}
        self.failure_threshold = 3  # Number of failures before switching
        self.recovery_time = timedelta(minutes=15)  # Time to wait before trying original again
        
    def setup_logger(self):
        self.logger = logging.getLogger('FallbackSystem')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('logs/system.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def record_failure(self, component: str):
        """Record a failure for a specific component"""
        current_time = datetime.now()
        
        if component not in self.failures:
            self.failures[component] = 0
            self.last_failure_time[component] = []
            
        self.failures[component] += 1
        self.last_failure_time[component].append(current_time)
        
        # Keep only recent failure times
        self.last_failure_time[component] = [
            t for t in self.last_failure_time[component]
            if current_time - t < timedelta(hours=1)
        ]
        
        self.logger.warning(f"Recorded failure for {component}. Total: {self.failures[component]}")
        
        # Check if we need to switch
        if self.failures[component] >= self.failure_threshold:
            self.logger.warning(f"Failure threshold reached for {component}. Activating fallback.")
            return True
            
        return False
    
    def should_use_fallback(self, component: str) -> bool:
        """Determine if we should use a fallback for this component"""
        if component not in self.failures:
            return False
            
        # If we've had enough failures, use fallback
        if self.failures[component] >= self.failure_threshold:
            # Check if enough time has passed to try original again
            last_failure = max(self.last_failure_time[component])
            if datetime.now() - last_failure > self.recovery_time:
                # Random chance to try original again (20%)
                if random.random() < 0.2:
                    self.logger.info(f"Trying original {component} again after recovery period")
                    self.failures[component] = 0
                    return False
                return True
            return True
            
        return False
    
    def get_fallback_for(self, component: str) -> str:
        """Get an appropriate fallback component"""
        fallback_map = {
            "voice_generation": ["edge_tts", "google_tts", "emergency_voice"],
            "content_generation": ["groq", "huggingface", "emergency_questions"],
            "image_processing": ["local_blur", "alternative_api", "static_images"],
            "youtube_api": ["backup_credentials", "alternative_method", "manual_review"]
        }
        
        if component in fallback_map:
            # Return next fallback in sequence (rotating)
            failures = self.failures.get(component, 0)
            fallback_index = (failures - self.failure_threshold) % len(fallback_map[component])
            return fallback_map[component][fallback_index]
            
        return "default_fallback"
    
    def reset_component(self, component: str):
        """Reset failure count for a component (after successful operation)"""
        if component in self.failures:
            self.failures[component] = 0
            self.logger.info(f"Reset failure count for {component}")
