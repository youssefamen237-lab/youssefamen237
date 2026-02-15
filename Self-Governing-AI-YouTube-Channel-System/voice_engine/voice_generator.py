import pyttsx3

# Initialize the text-to-speech engine
def voice_generator(text):
    engine = pyttsx3.init()
    engine.say(text)
    engine.runAndWait()

    return engine