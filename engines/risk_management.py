import os
import time
import logging
from datetime import datetime, timedelta

class RiskManagement:
    def __init__(self):
        self.setup_logger()
        self.risk_scores = {}
        self.last_action_time = {}
        self.action_counts = {}
        self.rate_limits = {
            "youtube_api": 10000,  # Max quota units per day
            "content_generation": 100,  # Max requests per hour
            "image_processing": 200,  # Max requests per hour
        }
        self.current_usage = {k: 0 for k in self.rate_limits}
        self.daily_reset_time = None
        self.strike_history = []
        self.max_strikes = 3  # Maximum strikes before major changes
        
    def setup_logger(self):
        self.logger = logging.getLogger('RiskManagement')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('logs/system.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def check_content_risk(self, content: dict) -> float:
        """Analyze content for potential YouTube policy violations"""
        risk_score = 0.0
        
        # Check for copyright risk
        if self._check_copyright_risk(content):
            risk_score += 0.4
            self.logger.warning("Content has potential copyright risk")
        
        # Check for reused content risk
        if self._check_reused_content_risk(content):
            risk_score += 0.3
            self.logger.warning("Content shows signs of reused content risk")
        
        # Check for misleading metadata
        if self._check_misleading_metadata(content):
            risk_score += 0.3
            self.logger.warning("Content has potential misleading metadata risk")
        
        # Log the risk assessment
        self.logger.info(f"Content risk assessment: {risk_score:.2f}")
        
        return risk_score
    
    def _check_copyright_risk(self, content: dict) -> bool:
        """Check if content might violate copyright policies"""
        # In a real system, this would use more sophisticated checks
        # This is a simplified version
        
        # Check if background image is from a known problematic source
        if content.get("background_source") and "copyrighted" in content["background_source"].lower():
            return True
            
        # Check if question content matches known copyrighted material
        if content.get("question_text"):
            # Would use database of known copyrighted questions in production
            pass
            
        return False
    
    def _check_reused_content_risk(self, content: dict) -> bool:
        """Check if content might be considered reused"""
        # Check if this is too similar to recently published content
        if content.get("similarity_score", 0) > 0.8:
            return True
            
        # Check publishing frequency
        now = datetime.now()
        if "last_publish" in self.last_action_time:
            time_since_last = now - self.last_action_time["last_publish"]
            if time_since_last < timedelta(minutes=15):
                return True  # Publishing too frequently
                
        return False
    
    def _check_misleading_metadata(self, content: dict) -> bool:
        """Check if metadata might be considered misleading"""
        # Check title for clickbait patterns
        title = content.get("title", "")
        clickbait_patterns = [
            "SHOCKING", "YOU WON'T BELIEVE", "CLICK NOW", 
            "MUST SEE", "IMPOSSIBLE", "SECRET", "HACK"
        ]
        
        for pattern in clickbait_patterns:
            if pattern.lower() in title.lower():
                return True
                
        # Check if title promises something the content doesn't deliver
        if "answer" in content and content["answer"] not in title:
            # Would do more sophisticated analysis in production
            pass
            
        return False
    
    def monitor_rate_limits(self, component: str, cost: int = 1):
        """Monitor and enforce rate limits"""
        now = datetime.now()
        
        # Reset daily counters if needed
        if (self.daily_reset_time is None or 
            now.date() != self.daily_reset_time.date()):
            self._reset_daily_counters()
            
        # Increment usage
        self.current_usage[component] += cost
        
        # Check if we're approaching limits
        usage_percent = (self.current_usage[component] / self.rate_limits[component]) * 100
        
        if usage_percent > 80:
            self.logger.warning(f"Rate limit approaching for {component}: {usage_percent:.1f}%")
            return False  # Should slow down
            
        if usage_percent > 95:
            self.logger.critical(f"Rate limit critical for {component}: {usage_percent:.1f}%")
            return False  # Must stop
            
        return True  # Within safe limits
    
    def _reset_daily_counters(self):
        """Reset daily rate limit counters"""
        self.daily_reset_time = datetime.now()
        for component in self.current_usage:
            self.current_usage[component] = 0
        self.logger.info("Reset daily rate limit counters")
    
    def record_strike(self, reason: str):
        """Record a YouTube strike against the channel"""
        now = datetime.now()
        self.strike_history.append({
            "timestamp": now,
            "reason": reason
        })
        
        self.logger.critical(f"RECEIVED STRIKE: {reason}. Total strikes: {len(self.strike_history)}")
        
        # Take immediate action based on strikes
        if len(self.strike_history) >= self.max_strikes:
            self._activate_emergency_protocol()
    
    def _activate_emergency_protocol(self):
        """Activate emergency protocol when strikes reach dangerous levels"""
        self.logger.critical("ACTIVATING EMERGENCY PROTOCOL - STRIKE COUNT CRITICAL")
        
        # Drastically reduce publishing frequency
        self.action_counts["publish"] = 0
        self.last_action_time["last_publish"] = datetime.now() + timedelta(hours=24)
        
        # Switch to most conservative content strategy
        self.logger.info("Switching to maximum safety content profile")
        
        # Notify system manager (would send email/notification in production)
        self.logger.warning("EMERGENCY: Channel at risk of termination. Immediate review required.")
    
    def should_modify_behavior(self) -> bool:
        """Determine if system should modify its behavior due to risk"""
        now = datetime.now()
        
        # Check recent strikes
        recent_strikes = [
            s for s in self.strike_history
            if now - s["timestamp"] < timedelta(days=7)
        ]
        
        if len(recent_strikes) >= 2:
            return True
            
        # Check rate limit usage
        for component, usage in self.current_usage.items():
            if usage / self.rate_limits[component] > 0.9:
                return True
                
        # Check publishing frequency
        if "last_publish" in self.last_action_time:
            time_since_last = now - self.last_action_time["last_publish"]
            if time_since_last < timedelta(minutes=30) and self.action_counts.get("publish", 0) > 10:
                return True  # Publishing too frequently
                
        return False
    
    def get_safety_adjustment(self) -> float:
        """Get a safety adjustment factor (0.0 to 1.0) for content generation"""
        now = datetime.now()
        
        # Base on strike history
        strike_factor = 1.0
        if self.strike_history:
            days_since_last = (now - self.strike_history[-1]["timestamp"]).days
            # More recent strikes mean higher safety needed
            strike_factor = max(0.3, 1.0 - (min(30, days_since_last) / 30) * 0.7)
        
        # Base on rate limit usage
        rate_factor = 1.0
        max_usage = max([u / self.rate_limits[c] for c, u in self.current_usage.items()])
        if max_usage > 0.8:
            rate_factor = 1.0 - (max_usage - 0.8) * 5  # Drops quickly above 80%
        
        # Base on publishing frequency
        freq_factor = 1.0
        if "last_publish" in self.last_action_time:
            time_since_last = now - self.last_action_time["last_publish"]
            # If publishing too frequently, increase safety
            if time_since_last < timedelta(minutes=45):
                freq_factor = 0.7
        
        # Combine factors
        safety_factor = min(strike_factor, rate_factor, freq_factor)
        
        # Log the calculation
        self.logger.debug(f"Safety adjustment: {safety_factor:.2f} "
                         f"(strikes: {strike_factor:.2f}, "
                         f"rate: {rate_factor:.2f}, "
                         f"freq: {freq_factor:.2f})")
        
        return safety_factor
    
    def record_action(self, action_type: str):
        """Record an action for rate limiting and risk analysis"""
        now = datetime.now()
        
        # Update action counts
        self.action_counts[action_type] = self.action_counts.get(action_type, 0) + 1
        
        # Update last action time
        self.last_action_time[action_type] = now
        
        # Check for suspicious patterns
        if action_type == "publish" and self.action_counts[action_type] > 5:
            time_since_first = now - self.last_action_time.get(f"{action_type}_first", now)
            if time_since_first < timedelta(hours=1):
                actions_per_hour = self.action_counts[action_type] / max(0.1, time_since_first.total_seconds() / 3600)
                if actions_per_hour > 10:  # More than 10 publishes per hour
                    self.logger.warning(f"Suspicious publishing pattern detected: {actions_per_hour:.1f}/hour")
