import random
import nltk
from nltk.corpus import wordnet

# Ensure the necessary NLTK data is downloaded
nltk.download('wordnet')

# Define a function to generate a question
def generate_question():
    # Select a random noun from the WordNet corpus
    noun = random.choice(list(wordnet.all_synsets('n')))
    
    # Generate a question based on the noun
    question = f'What is {noun.lemmas()[0].name()}?'
    
    return question