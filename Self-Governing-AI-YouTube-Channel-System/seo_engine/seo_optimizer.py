import re
import random

# SEO keyword database
SEO_KEYWORDS = [
    'facts', 'trivia', 'interesting', 'amazing', 'cool', 'mind blowing', 'knowledge', 
    'education', 'learn', 'how to', 'tips', 'secrets', 'facts', 'truth', 'surprising',
    'fun', 'easy', 'simple', 'quick', 'fast', 'best', 'top', 'ultimate', 'complete'
]

SEO_TITLES = [
    "{prefix} {question} - {keyword}",
    "{keyword} About {question}",
    "Amazing Facts About {question}",
    "You Won't Believe This About {question}",
    "{question} Explained Simply"
]

SEO_DESCRIPTIONS = [
    "Learn amazing facts about {question} in this quick video. {keyword} facts and more!",
    "Discover interesting information about {question}. Perfect for {keyword} learners!",
    "Get ready to be amazed with these {keyword} facts about {question}.",
    "This {keyword} video explains {question} in a fun and easy way.",
    "Find out {keyword} information about {question} in this informative video."
]


def optimize_title(question, prefix="Amazing", keyword=None):
    """
    Optimize a title for YouTube SEO
    
    Args:
        question (str): The question being asked
        prefix (str): Prefix for the title
        keyword (str): Keyword to include in title
    
    Returns:
        str: Optimized title
    """
    if not keyword:
        keyword = random.choice(SEO_KEYWORDS)
    
    # Select a title template
    template = random.choice(SEO_TITLES)
    
    # Format the title
    title = template.format(
        prefix=prefix,
        question=question[:50],  # Limit length
        keyword=keyword
    )
    
    # Remove special characters and limit length
    title = re.sub(r'[^\w\s\-\'\"]', '', title)
    title = title[:100]  # YouTube title limit
    
    return title.strip()


def optimize_description(question, keyword=None):
    """
    Optimize a description for YouTube SEO
    
    Args:
        question (str): The question being asked
        keyword (str): Keyword to include in description
    
    Returns:
        str: Optimized description
    """
    if not keyword:
        keyword = random.choice(SEO_KEYWORDS)
    
    # Select a description template
    template = random.choice(SEO_DESCRIPTIONS)
    
    # Format the description
    description = template.format(
        question=question[:100],
        keyword=keyword
    )
    
    # Remove special characters and limit length
    description = re.sub(r'[^\w\s\-\'\.\,\!\?\;\:]', '', description)
    description = description[:5000]  # YouTube description limit
    
    return description.strip()


def generate_tags(question, keyword=None):
    """
    Generate SEO tags for the video
    
    Args:
        question (str): The question being asked
        keyword (str): Keyword to include in tags
    
    Returns:
        list: List of tags
    """
    if not keyword:
        keyword = random.choice(SEO_KEYWORDS)
    
    # Basic tag generation
    base_tags = [
        question.split()[0] if question.split() else 'fact',  # First word of question
        keyword,
        'facts',
        'trivia',
        'education',
        'learning',
        'knowledge'
    ]
    
    # Add some common SEO tags
    common_tags = [
        'fun',
        'interesting',
        'amazing',
        'cool',
        'educational',
        'informative'
    ]
    
    # Combine and deduplicate
    all_tags = list(set(base_tags + common_tags))
    
    # Limit to reasonable number
    return all_tags[:15]


def clean_text_for_seo(text):
    """
    Clean text for SEO purposes
    
    Args:
        text (str): Input text
    
    Returns:
        str: Cleaned text
    """
    # Remove special characters but keep spaces
    cleaned = re.sub(r'[^\w\s\-\'\"]', '', text)
    
    # Replace multiple spaces with single space
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    return cleaned.strip()

# Test the SEO optimizer
if __name__ == '__main__':
    test_question = "What is the capital of France?"
    
    print("Testing SEO optimization:")
    print(f"Original question: {test_question}")
    
    title = optimize_title(test_question)
    print(f"Optimized title: {title}")
    
    description = optimize_description(test_question)
    print(f"Optimized description: {description}")
    
    tags = generate_tags(test_question)
    print(f"Generated tags: {tags}")
