import pyttsx3\n
engine = pyttsx3.init()\n
def voice_generator(text):\n    engine.say(text)\n    engine.runAndWait()\n    return engine