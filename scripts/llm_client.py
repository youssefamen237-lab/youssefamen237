import requests
import json
import logging
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from .config import Config

logger = logging.getLogger("llm_client")
handler = logging.FileHandler(Config.LOG_DIR / "llm_client.log")
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

class LLMClient:
    def __init__(self):
        self.gemini_key = Config.GEMINI_API_KEY
        self.groq_key = Config.GROQ_API_KEY

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2), retry=retry_if_exception_type(Exception))
    def generate(self, prompt: str) -> str:
        """Try Gemini first, then Groq."""
        if self.gemini_key:
            try:
                logger.info("Attempting Gemini generation.")
                return self._call_gemini(prompt)
            except Exception as e:
                logger.warning(f"Gemini failed: {e}")

        if self.groq_key:
            try:
                logger.info("Attempting Groq generation.")
                return self._call_groq(prompt)
            except Exception as e:
                logger.warning(f"Groq failed: {e}")

        raise RuntimeError("All LLM providers failed.")

    def _call_gemini(self, prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={self.gemini_key}"
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": prompt}]}
            ]
        }
        response = requests.post(url, json=body, timeout=30)
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return text.strip()

    def _call_groq(self, prompt: str) -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "mixtral-8x7b-32768",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    # Convenience wrappers for specific content generation

    def generate_question(self) -> dict:
        """Generate a quiz question with answer in JSON format."""
        prompt = (
            "Generate ONE quiz question suitable for a YouTube Short. "
            "Choose ONE of the following formats: True/False, Multiple Choice (4 options), Direct Question, Guess the Answer, "
            "Quick Challenge, Only Geniuses, Memory Test, Visual Question. "
            "Provide the question text, the type, the options (if applicable), and the correct answer. "
            "Return the data as a JSON object with keys: type, question, options (optional), answer."
        )
        raw = self.generate(prompt)
        try:
            data = json.loads(raw)
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse question JSON: {e}")
            raise

    def generate_seo_title(self, question_text: str) -> str:
        prompt = (
            f"Write a compelling, click‑bait style YouTube Shorts title for the following quiz question: \"{question_text}\". "
            "The title must be under 70 characters, contain no duplicate phrasing from recent titles, "
            "and include an attention‑grabbing hook."
        )
        title = self.generate(prompt).strip()
        # Remove surrounding quotes if any
        if title.startswith('"') and title.endswith('"'):
            title = title[1:-1]
        return title

    def generate_seo_description(self, question_text: str) -> str:
        prompt = (
            f"Write a YouTube Shorts description (150‑200 words) for a quiz video featuring the question: \"{question_text}\". "
            "Include a short introduction, a CTA encouraging comments, likes, and subscriptions, and a list of relevant hashtags. "
            "Do not repeat any phrase from recent descriptions."
        )
        return self.generate(prompt).strip()

    def generate_tags(self, title: str) -> list:
        prompt = (
            f"Provide a list of up to 15 SEO‑optimized YouTube tags (single words) relevant to the video titled \"{title}\". "
            "Separate tags with commas."
        )
        raw = self.generate(prompt)
        tags = [t.strip() for t in raw.split(",") if t.strip()]
        return tags[:15]

    def generate_hashtags(self, title: str) -> list:
        prompt = (
            f"Generate 5 relevant, trending YouTube hashtags for a short quiz video titled \"{title}\". "
            "Return them as a comma‑separated list."
        )
        raw = self.generate(prompt)
        hashtags = [h.strip() for h in raw.split(",") if h.strip()]
        return hashtags[:5]
