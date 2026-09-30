TOOL_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "multimodal-ai": [
        "text-to-image", "text-to-video", "image generation", "video generation",
        "vision model", "multimodal", "sora", "midjourney", "dall-e", "dalle",
        "stable diffusion", "runway", "flux", "veo",
    ],
    "robotics": [
        "robot", "robotics", "humanoid", "boston dynamics", "drone", "actuator",
    ],
    "agents": [
        "ai agent", "agentic", "autonomous agent", "multi-agent", "auto-gpt",
        "autogpt", "workflow automation", "n8n", "crewai",
    ],
    "llm": [
        "llm", "language model", "gpt", "chatgpt", "claude", "gemini", "llama",
        "mistral", "grok", "chatbot", "copilot", "perplexity",
    ],
}

KNOWN_TOOLS: list[str] = [
    "ChatGPT", "Claude", "Gemini", "Midjourney", "DALL-E", "Stable Diffusion",
    "Sora", "Runway", "Perplexity", "GitHub Copilot", "Copilot", "Llama",
    "Mistral", "Grok", "Notion AI", "AutoGPT", "LangChain", "CrewAI", "n8n",
    "Veo", "Flux",
]

DEFAULT_TOOL_NAME = "General AI Tools"

def classify_tool_category(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    for category, keywords in TOOL_CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "general-ai"

def extract_tool_name(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    for tool in KNOWN_TOOLS:
        if tool.lower() in text:
            return tool
    return DEFAULT_TOOL_NAME