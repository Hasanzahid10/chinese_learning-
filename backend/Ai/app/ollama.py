import json

import requests

from .config import settings


def stream_chat(messages):

    response = requests.post(
        f"{settings.ollama_url}/api/chat",
        json={
            "model": settings.ollama_model,
            "messages": messages,
            "stream": True,
            "keep_alive": "30m",
            "options": {
                "temperature": 0.7,
                "num_ctx": 2048,
                "num_predict": 80,
            },
        },
        stream=True,
        timeout=300,
    )

    response.raise_for_status()

    for line in response.iter_lines():

        if not line:
            continue

        data = json.loads(line)

        if "message" in data:

            content = data["message"].get(
                "content",
                "",
            )

            if content:
                yield content

        if data.get("done"):
            break
