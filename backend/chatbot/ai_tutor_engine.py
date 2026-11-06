"""
AI Chinese Tutor Engine
Multi-provider LLM integration supporting:
- Groq (Free: LLaMA 3.3 70B / LLaMA 3.1 8B)
- Google Gemini (Free: Gemini 1.5 Flash / Gemini 2.0 Flash)
- OpenAI / OpenRouter
- Local Ollama (Offline: Qwen 2.5)
- Automated Pinyin via pypinyin
- Dynamic HSK 1-6 vocabulary extraction from the 5,408-word database
- Intelligent offline fallback dialogue system
"""
import os
import json
import re
import time
import threading
import requests
from typing import Dict, Any, List, Optional
from dictionary.models import HSKWord

try:
    import pypinyin
except ImportError:
    pypinyin = None

# Native Chinese Conversation Partner System Prompt
SYSTEM_PROMPT = """你是一个真实、自然、友好的中文聊天伙伴。
你正在和一个正在学习中文的人聊天。你的目标是和他进行自然、轻松的日常对话。
把用户当作朋友，而不是学生。

【聊天原则】
- 默认使用中文。
- 自然地回应用户刚刚说的话。
- 保持当前话题，不要突然换话题。
- 回复通常只需要一两句话。
- 像普通朋友聊天一样说话。
- 可以表达自己的反应、想法、感受和态度。
- 如果用户的中文有小错误，但意思清楚，不要主动纠错，直接自然接话。
- 语气轻松、真诚，不要像机器人。
"""

def _get_env_key(key_name: str) -> str:
    """Reads environment variable from os.environ or .env file."""
    val = os.getenv(key_name, "").strip()
    if val:
        return val

    # Try loading from backend .env
    from pathlib import Path
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{key_name}=") or line.startswith(f"{key_name} ="):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            return parts[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return ""


def _generate_sentence_pinyin(chinese_text: str) -> str:
    """Generates tone-marked pinyin for any Chinese sentence using pypinyin."""
    if not chinese_text:
        return ""
    if pypinyin:
        try:
            tokens = pypinyin.lazy_pinyin(
                chinese_text,
                style=pypinyin.Style.TONE,
                errors='default'
            )
            return " ".join(tokens)
        except Exception:
            pass
    return ""


def _extract_vocabulary_from_text(chinese_text: str, limit: int = 4) -> List[Dict[str, str]]:
    """Extracts genuine HSK words from the 5,408-word database present in the text."""
    if not chinese_text:
        return []

    # Clean punctuation
    cleaned_hanzi = re.sub(r'[^\u4e00-\u9fff]', '', chinese_text)
    if not cleaned_hanzi:
        return []

    extracted: List[Dict[str, str]] = []
    seen = set()

    # Query multi-character words first for richer vocabulary breakdown
    all_words = HSKWord.objects.filter(chinese__isnull=False)
    for word in all_words:
        ch = word.chinese.strip()
        if len(ch) >= 2 and ch in cleaned_hanzi and ch not in seen:
            seen.add(ch)
            meaning = word.bangla if word.bangla else word.english
            pinyin_val = word.pinyin if word.pinyin else _generate_sentence_pinyin(ch)
            extracted.append({
                "chinese": ch,
                "pinyin": pinyin_val,
                "bangla": f"{word.english} ({meaning})" if word.english and word.bangla else (meaning or word.english or ""),
            })
            if len(extracted) >= limit:
                break

    # If fewer than 2 words found, allow single character common words
    if len(extracted) < 2:
        for word in all_words:
            ch = word.chinese.strip()
            if len(ch) == 1 and ch in cleaned_hanzi and ch not in seen:
                seen.add(ch)
                meaning = word.bangla if word.bangla else word.english
                pinyin_val = word.pinyin if word.pinyin else _generate_sentence_pinyin(ch)
                extracted.append({
                    "chinese": ch,
                    "pinyin": pinyin_val,
                    "bangla": f"{word.english} ({meaning})" if word.english and word.bangla else (meaning or word.english or ""),
                })
                if len(extracted) >= limit:
                    break

    return extracted


# Concurrency and Load Balancing State
_dispatch_lock = threading.Lock()
_request_counter = 0
_gemini_cooldown_until = 0.0
_groq_cooldown_until = 0.0


def _call_groq(messages: List[Dict[str, str]], api_key: str) -> Optional[str]:
    """Queries Groq API with Qwen 27B or available models for rapid Chinese conversation."""
    models_to_try = [
        "qwen/qwen3.8-27b",
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
    ]
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for model in models_to_try:
        try:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 200,
            }
            res = requests.post(url, headers=headers, json=payload, timeout=9)
            if res.status_code == 200:
                data = res.json()
                content = data["choices"][0]["message"]["content"].strip()
                if content:
                    return content
            elif res.status_code in [429, 503]:
                global _groq_cooldown_until
                _groq_cooldown_until = time.time() + 45.0
                print(f"[AI Engine] Groq model {model} busy/rate-limited ({res.status_code}), cooldown set.")
            else:
                print(f"[AI Engine] Groq model {model} status {res.status_code}: {res.text[:120]}")
        except Exception as e:
            print(f"[AI Engine] Groq API call for {model} failed: {e}")
    return None


def _call_gemini(messages: List[Dict[str, str]], api_key: str) -> Optional[str]:
    """Queries Google Gemini API with automatic flash model fallbacks."""
    models_to_try = [
        "gemini-3.6-flash",
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        "gemini-flash-latest",
        "gemini-3.1-flash-lite",
    ]
    headers = {"Content-Type": "application/json"}

    # Separate system instruction if present, or format contents
    system_text = ""
    contents = []
    for m in messages:
        if m["role"] == "system":
            system_text = m["content"]
        else:
            role = "user" if m["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": m["content"]}]
            })

    payload = {"contents": contents}
    if system_text:
        payload["system_instruction"] = {
            "parts": [{"text": system_text}]
        }

    for model in models_to_try:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            res = requests.post(url, headers=headers, json=payload, timeout=9)
            if res.status_code == 200:
                data = res.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
            elif res.status_code in [429, 503]:
                global _gemini_cooldown_until
                _gemini_cooldown_until = time.time() + 45.0
                print(f"[AI Engine] Gemini {model} busy/rate-limited ({res.status_code}), trying next fallback model...")
                continue
            else:
                print(f"[AI Engine] Gemini {model} status {res.status_code}: {res.text[:120]}")
        except Exception as e:
            print(f"[AI Engine] Gemini API call for {model} failed: {e}")
            continue
    return None


def _call_ollama(messages: List[Dict[str, str]], ollama_url: str, model: str) -> Optional[str]:
    """Queries local Ollama instance if active."""
    try:
        url = f"{ollama_url.rstrip('/')}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 120},
        }
        res = requests.post(url, json=payload, timeout=8)
        if res.status_code == 200:
            data = res.json()
            return data.get("message", {}).get("content", "").strip()
    except Exception:
        pass
    return None


def _call_openai(messages: List[Dict[str, str]], api_key: str) -> Optional[str]:
    """Queries OpenAI compatible endpoint."""
    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 150,
        }
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[AI Engine] OpenAI API call failed: {e}")
    return None


def _query_multi_provider_llm(conversation, user_text: str, hsk_level: int = 1) -> Optional[str]:
    """
    Intelligent Multi-Provider Dispatcher with Rush Load Balancing:
    1. Gemini: 1st Priority
    2. Groq: 2nd Priority & Burst/Rush Load Balancer
    3. Seamless Automatic Failover (If one fails, immediately try the other)
    4. Extended Fallbacks: OpenAI -> Ollama -> Database
    """
    global _request_counter, _gemini_cooldown_until, _groq_cooldown_until

    # 1. Build Conversation History Context
    history_messages = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\nTarget learner proficiency: HSK {hsk_level}. Reply in 1-2 natural Chinese sentences. After the Chinese sentence, you may add a brief English translation in brackets."}
    ]

    if conversation:
        try:
            previous = list(conversation.messages.order_by("-created_at")[:8])
            previous.reverse()
            for msg in previous:
                role = "assistant" if msg.role == "assistant" else "user"
                history_messages.append({"role": role, "content": msg.content})
        except Exception:
            pass

    history_messages.append({"role": "user", "content": user_text})

    gemini_key = _get_env_key("GEMINI_API_KEY")
    groq_key = _get_env_key("GROQ_API_KEY")

    with _dispatch_lock:
        _request_counter += 1
        req_count = _request_counter

    now = time.time()
    gemini_cooling = now < _gemini_cooldown_until
    groq_cooling = now < _groq_cooldown_until

    # Dispatch Priority Strategy:
    # - Gemini is primary (1st priority).
    # - If heavy user rush or Gemini is cooling (recent 429/503), balance ~25% load or cooldown to Groq.
    # - In either case, if the chosen primary fails, it seamlessly and immediately executes the other!
    rush_divert_to_groq = bool(
        gemini_key and groq_key and not groq_cooling and (gemini_cooling or (req_count % 4 == 0))
    )

    if rush_divert_to_groq:
        primary_order = [("groq", groq_key), ("gemini", gemini_key)]
    else:
        primary_order = [("gemini", gemini_key), ("groq", groq_key)]

    for provider, key in primary_order:
        if not key:
            continue
        try:
            if provider == "gemini":
                reply = _call_gemini(history_messages, key)
                if reply:
                    return reply
                print("[AI Engine] Gemini call returned empty/failed, failing over to backup...")
            elif provider == "groq":
                reply = _call_groq(history_messages, key)
                if reply:
                    return reply
                print("[AI Engine] Groq call returned empty/failed, failing over to backup...")
        except Exception as e:
            print(f"[AI Engine] Provider {provider} failed with exception: {e}")

    # Provider 3: OpenAI (if configured)
    openai_key = _get_env_key("OPENAI_API_KEY")
    if openai_key:
        reply = _call_openai(history_messages, openai_key)
        if reply:
            return reply

    # Provider 4: Local Ollama (if running)
    ollama_url = _get_env_key("OLLAMA_URL") or "http://127.0.0.1:11434"
    ollama_model = _get_env_key("OLLAMA_MODEL") or "qwen2.5:3b"
    reply = _call_ollama(history_messages, ollama_url, ollama_model)
    if reply:
        return reply

    return None


def _find_matching_hsk_words(query: str, limit: int = 4) -> List[Dict[str, str]]:
    """Searches the 5,400+ HSKWord database for matching vocabulary."""
    cleaned = query.strip()
    if not cleaned:
        return []

    words = HSKWord.objects.filter(chinese__icontains=cleaned)[:limit]
    if not words.exists():
        words = HSKWord.objects.filter(english__icontains=cleaned)[:limit]
    if not words.exists():
        words = HSKWord.objects.filter(bangla__icontains=cleaned)[:limit]

    results = []
    for w in words:
        results.append({
            "chinese": w.chinese,
            "pinyin": w.pinyin,
            "bangla": f"{w.english} ({w.bangla})" if w.bangla else w.english,
        })
    return results


def _generate_fallback_response(user_text: str, user, hsk_level: int = 1) -> Dict[str, Any]:
    """Database-backed dynamic fallback response if cloud LLM has not been configured."""
    text_lower = user_text.lower().strip()

    if any(k in text_lower for k in ["hello", "hi", "greet", "salutation", "সালাম", "হ্যালো", "অভিবাদন", "你好"]):
        return {
            "chinese": "你好！很高兴和你聊天。今天你想练习什么话题？",
            "pinyin": "Nǐ hǎo! Hěn gāoxìng hé nǐ liáotiān. Jīntiān nǐ xiǎng liànxí shénme huàtí?",
            "bangla": "Hello! Nice to chat with you. What topic would you like to practice today?",
            "vocabulary": [
                {"chinese": "你好", "pinyin": "nǐ hǎo", "bangla": "Hello (হ্যালো)"},
                {"chinese": "聊天", "pinyin": "liáotiān", "bangla": "To chat (আলাপ করা)"},
                {"chinese": "练习", "pinyin": "liànxí", "bangla": "Practice (অনুশীলন)"},
                {"chinese": "话题", "pinyin": "huàtí", "bangla": "Topic (বিষয়)"},
            ],
            "content": "你好！很高兴和你聊天。今天你想练习什么话题？\n(Hello! Nice to chat with you. What topic would you like to practice today?)"
        }

    if any(k in text_lower for k in ["food", "restaurant", "order", "eat", "menu", "খাবার", "অর্ডার", "রেস্তোরাঁ", "খেতে"]):
        return {
            "chinese": "好的！在餐厅点餐时可以说：服务员，我想点菜，请给我菜单。",
            "pinyin": "Hǎo de! Zài cāntīng diǎncān shí kěyǐ shuō: Fúwùyuán, wǒ xiǎng diǎncài, qǐng gěi wǒ càidān.",
            "bangla": "Great! When ordering at a restaurant: 'Waiter, I'd like to order, please give me the menu.'",
            "vocabulary": [
                {"chinese": "点餐", "pinyin": "diǎncān", "bangla": "To order food (খাবার অর্ডার)"},
                {"chinese": "服务员", "pinyin": "fúwùyuán", "bangla": "Waiter (পরিবেশক)"},
                {"chinese": "菜单", "pinyin": "càidān", "bangla": "Menu (মেনু)"},
            ],
            "content": "好的！在餐厅点餐时可以说：服务员，我想点菜，请给我菜单。\n(Waiter, I'd like to order, please give me the menu.)"
        }

    matched_words = _find_matching_hsk_words(user_text)
    if matched_words:
        top_word = matched_words[0]
        return {
            "chinese": f"关于“{top_word['chinese']}”，它的意思是：{top_word['bangla']}。我们可以用它造句吗？",
            "pinyin": f"Guānyú \"{top_word['chinese']}\", tā de yìsi shì: {top_word['bangla']}. Wǒmen kěyǐ yòng tā zàojù ma?",
            "bangla": f"Regarding '{top_word['chinese']}': It means {top_word['bangla']}. Shall we try making a sentence with it?",
            "vocabulary": matched_words,
            "content": f"关于“{top_word['chinese']}”，它的意思是：{top_word['bangla']}。我们可以用它造句吗？"
        }

    return {
        "chinese": "听起来很有意思！请多跟我用中文聊聊，我们可以一起练习。",
        "pinyin": "Tīng qǐlái hěn yǒu yìsi! Qǐng duō gēn wǒ yòng zhōngwén liáoliao, wǒmen kěyǐ yìqǐ liànxí.",
        "bangla": "That sounds very interesting! Keep chatting with me in Chinese, and let's practice together.",
        "vocabulary": [
            {"chinese": "有意思", "pinyin": "yǒu yìsi", "bangla": "Interesting (আকর্ষণীয়)"},
            {"chinese": "中文", "pinyin": "zhōngwén", "bangla": "Chinese language (চীনা ভাষা)"},
            {"chinese": "练习", "pinyin": "liànxí", "bangla": "Practice (অনুশীলন)"},
        ],
        "content": "听起来很有意思！请多跟我用中文聊聊，我们可以一起练习。"
    }


def generate_ai_tutor_response(conversation, user_text: str, user, hsk_level: int = 1) -> Dict[str, Any]:
    """
    Main entry point for generating AI tutoring responses.
    1. Tries configured cloud/local LLM with full conversation history.
    2. Automatically generates tone-marked Pinyin.
    3. Automatically extracts genuine HSK vocabulary words from the sentence.
    4. Falls back to database dialog generator if no LLM key is configured.
    """
    llm_output = _query_multi_provider_llm(conversation, user_text, hsk_level)

    if llm_output:
        # Separate Chinese sentence and English/Bangla translation if formatted
        chinese_part = llm_output
        meaning_part = ""

        # Check for bracketed English translation e.g. "你好！ [Hello!]"
        bracket_match = re.search(r'[\(\[\{]([^\)\]\}]+)[\)\]\}]', llm_output)
        if bracket_match:
            meaning_part = bracket_match.group(1).strip()
            chinese_part = llm_output[:bracket_match.start()].strip() + " " + llm_output[bracket_match.end():].strip()
            chinese_part = chinese_part.strip()

        # Compute full sentence pinyin
        pinyin_text = _generate_sentence_pinyin(chinese_part)

        # Extract genuine HSK words from the sentence
        vocab = _extract_vocabulary_from_text(chinese_part, limit=4)

        return {
            "chinese": chinese_part if chinese_part else llm_output,
            "pinyin": pinyin_text,
            "bangla": meaning_part if meaning_part else "Conversational Chinese Response",
            "vocabulary": vocab,
            "content": llm_output,
        }

    # Otherwise use database-backed interactive dialog generator
    return _generate_fallback_response(user_text, user, hsk_level)
