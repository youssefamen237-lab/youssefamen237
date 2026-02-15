import requests
import os
import random
from PIL import Image, ImageDraw, ImageFont
import io
from config import (
    PEXELS_API_KEY, PIXABAY_API_KEY, UNSPLASH_ACCESS_KEY,
    BACKGROUND_DIR, THUMBNAILS_DIR
)

class ImageManager:
    def __init__(self):
        self.pexels_headers = {"Authorization": PEXELS_API_KEY} if PEXELS_API_KEY else {}
        self.pixabay_key = PIXABAY_API_KEY
        self.unsplash_key = UNSPLASH_ACCESS_KEY
        
        # Ensure directories exist
        os.makedirs(BACKGROUND_DIR, exist_ok=True)
        os.makedirs(THUMBNAILS_DIR, exist_ok=True)
    
    def download_random_background(self):
        """Download a random background image from various sources"""
        # Try different sources
        sources = [self._get_from_pexels, self._get_from_pixabay, self._get_from_unsplash]
        random.shuffle(sources)
        
        for source_func in sources:
            try:
                image_url = source_func()
                if image_url:
                    return self._download_image(image_url, BACKGROUND_DIR)
            except Exception as e:
                print(f"Failed to get background from {source_func.__name__}: {e}")
                continue
        
        # If all external sources fail, create a default background
        return self._create_default_background()
    
    def _get_from_pexels(self):
        """Get a random image from Pexels"""
        if not self.pexels_headers:
            return None
            
        url = "https://api.pexels.com/v1/search"
        params = {
            'query': 'abstract background pattern',
            'per_page': 1,
            'page': random.randint(1, 100)
        }
        
        response = requests.get(url, headers=self.pexels_headers, params=params)
        if response.status_code == 200:
            data = response.json()
            if data['photos']:
                return data['photos'][0]['src']['large']
        return None
    
    def _get_from_pixabay(self):
        """Get a random image from Pixabay"""
        if not self.pixabay_key:
            return None
            
        url = "https://pixabay.com/api/"
        params = {
            'key': self.pixabay_key,
            'q': 'abstract background',
            'image_type': 'photo',
            'per_page': 1,
            'page': random.randint(1, 50)
        }
        
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            if data['hits']:
                return data['hits'][0]['webformatURL']
        return None
    
    def _get_from_unsplash(self):
        """Get a random image from Unsplash"""
        if not self.unsplash_key:
            return None
            
        url = "https://api.unsplash.com/photos/random"
        headers = {"Authorization": f"Client-ID {self.unsplash_key}"}
        params = {
            'query': 'abstract background',
            'orientation': 'portrait'
        }
        
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            return data['urls']['regular']
        return None
    
    def _download_image(self, url, directory):
        """Download an image from URL to directory"""
        try:
            response = requests.get(url)
            if response.status_code == 200:
                # Generate a unique filename
                filename = f"bg_{len(os.listdir(directory)) + 1:04d}.jpg"
                filepath = os.path.join(directory, filename)
                
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                
                return filepath
        except Exception as e:
            print(f"Error downloading image: {e}")
        
        return None
    
    def _create_default_background(self):
        """Create a default background if no external images are available"""
        filename = f"bg_default_{random.randint(1000, 9999)}.jpg"
        filepath = os.path.join(BACKGROUND_DIR, filename)
        
        # Create a simple gradient background
        img = Image.new('RGB', (1080, 1920), color=(50, 50, 70))
        
        # Add some geometric patterns
        draw = ImageDraw.Draw(img)
        for i in range(20):
            x1 = random.randint(0, 1080)
            y1 = random.randint(0, 1920)
            x2 = x1 + random.randint(50, 200)
            y2 = y1 + random.randint(50, 200)
            color = tuple(random.randint(60, 100) for _ in range(3))
            draw.rectangle([x1, y1, x2, y2], fill=color, outline=None)
        
        img.save(filepath)
        return filepath
    
    def create_thumbnail(self, question, template_type):
        """Create a custom thumbnail for the video"""
        filename = f"thumb_{len(os.listdir(THUMBNAILS_DIR)) + 1:04d}.jpg"
        filepath = os.path.join(THUMBNAILS_DIR, filename)
        
        # Create a vertical thumbnail (9:16 aspect ratio)
        img = Image.new('RGB', (1080, 1920), color=(30, 30, 50))
        draw = ImageDraw.Draw(img)
        
        # Add title text
        try:
            # Try to use a better font if available
            font = ImageFont.truetype("arial.ttf", 60)
        except:
            # Fallback to default font
            font = ImageFont.load_default()
        
        # Draw the question text (first 60 chars)
        question_preview = (question[:60] + "...") if len(question) > 60 else question
        bbox = draw.textbbox((0, 0), question_preview, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (1080 - text_width) // 2
        y = 300
        
        # Draw text with outline
        outline_color = (0, 0, 0)
        main_color = (255, 255, 255)
        
        # Outline
        draw.text((x-2, y-2), question_preview, font=font, fill=outline_color)
        draw.text((x+2, y-2), question_preview, font=font, fill=outline_color)
        draw.text((x-2, y+2), question_preview, font=font, fill=outline_color)
        draw.text((x+2, y+2), question_preview, font=font, fill=outline_color)
        
        # Main text
        draw.text((x, y), question_preview, font=font, fill=main_color)
        
        # Add template type indicator
        try:
            small_font = ImageFont.truetype("arial.ttf", 40)
        except:
            small_font = ImageFont.load_default()
        
        template_text = f"Template: {template_type}"
        bbox = draw.textbbox((0, 0), template_text, font=small_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        
        draw.text(((1080 - tw) // 2, 500), template_text, font=small_font, fill=(200, 200, 255))
        
        # Add decorative elements
        for i in range(30):
            x_pos = random.randint(0, 1080)
            y_pos = random.randint(0, 1920)
            radius = random.randint(5, 20)
            color = tuple(random.randint(100, 200) for _ in range(3))
            draw.ellipse([x_pos-radius, y_pos-radius, x_pos+radius, y_pos+radius], fill=color)
        
        img.save(filepath)
        return filepath
