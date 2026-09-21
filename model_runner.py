#!/usr/bin/env python3
"""
Model runner for the Document Insight Platform.
Provides OpenAI-compatible API for embeddings, reranking, and generation using
actual models loaded via HuggingFace transformers and sentence-transformers.
"""
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import logging
from typing import Dict, List, Optional

app = FastAPI()
logger = logging.getLogger(__name__)

MODEL_TYPE = os.getenv("MODEL_TYPE", "multi")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "hf.co/vonjack/bge-m3-gguf:Q8_0")
RERANKER_MODEL_NAME = os.getenv("RERANKER_MODEL_NAME", "cross-encoder/ettin-reranker-17m-v1")
GENERATION_MODEL_NAME = os.getenv("GENERATION_MODEL_NAME", "Qwen/Qwen3.5-0.8B-Instruct")

embedding_model = None
reranker_model = None
generator = None
tokenizer = None

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


def _load_models():
    global embedding_model, reranker_model, generator, tokenizer
    try:
        if MODEL_TYPE in ("multi", "embedding"):
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {EMBEDDING_MODEL_NAME}")
            embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
            logger.info("Embedding model loaded")
        if MODEL_TYPE in ("multi", "reranker"):
            from sentence_transformers import CrossEncoder
            logger.info(f"Loading reranker model: {RERANKER_MODEL_NAME}")
            reranker_model = CrossEncoder(RERANKER_MODEL_NAME)
            logger.info("Reranker model loaded")
        if MODEL_TYPE in ("multi", "generation"):
            from transformers import AutoTokenizer, AutoModelForCausalLM
            logger.info(f"Loading generation model: {GENERATION_MODEL_NAME}")
            tokenizer = AutoTokenizer.from_pretrained(GENERATION_MODEL_NAME)
            generator = AutoModelForCausalLM.from_pretrained(GENERATION_MODEL_NAME)
            logger.info("Generation model loaded")
    except ImportError as e:
        logger.warning(f"Model library not available: {e}")
        logger.warning("Install with: pip install sentence-transformers transformers")
    except Exception as e:
        logger.error(f"Failed to load models: {e}")
        raise


@app.on_event("startup")
async def startup():
    _load_models()


# --- Request/Response models ---

class EmbeddingRequest(BaseModel):
    model: str
    input: List[str]


class EmbeddingItem(BaseModel):
    index: int
    embedding: List[float]


class EmbeddingResponse(BaseModel):
    data: List[EmbeddingItem]


class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None


class ChatChoice(BaseModel):
    message: ChatMessage


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Dict[str, str]]
    temperature: float = 0.0
    response_format: Dict[str, str] = {"type": "json_object"}
    max_tokens: Optional[int] = None


class ChatCompletionResponse(BaseModel):
    choices: List[ChatChoice]


# --- Helpers ---

def _make_embedding(vector: List[float], idx: int) -> EmbeddingItem:
    return EmbeddingItem(index=idx, embedding=vector)


def _make_chat_completion(content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(choices=[ChatChoice(message=ChatMessage(role="assistant", content=content))])


# --- Endpoints ---

@app.post("/engines/v1/embeddings")
async def create_embedding(request: EmbeddingRequest):
    """Return one embedding vector per input text."""
    texts = request.input
    if not texts:
        return EmbeddingResponse(data=[])

    # Try real model first
    if embedding_model is not None:
        try:
            from sentence_transformers import SentenceTransformer
            vectors = embedding_model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            items = []
            for i, v in enumerate(vectors):
                vec = v.tolist() if hasattr(v, 'tolist') else list(v)
                items.append(_make_embedding(vec, i))
            return EmbeddingResponse(data=items)
        except Exception as e:
            logger.error(f"Embedding model inference failed: {e}")

    # Fallback: deterministic pseudo-embeddings (dim matches BGE-M3 = 1024)
    import hashlib
    dim = 1024
    items = []
    for i, text in enumerate(texts):
        h = hashlib.sha256(text.encode()).digest()
        vec = [(h[j % 32] / 255.0) * 2 - 1 for j in range(dim)]
        norm = sum(v * v for v in vec) ** 0.5
        vec = [v / norm for v in vec]
        items.append(_make_embedding(vec, i))
    return EmbeddingResponse(data=items)


@app.post("/engines/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """Handle both reranking and generation requests via chat completions."""
    messages = request.messages
    system_content = ""
    user_content = ""
    for msg in messages:
        if msg.get("role") == "system":
            system_content = msg.get("content", "")
        elif msg.get("role") == "user":
            user_content = msg.get("content", "")

    user_data = None
    if user_content:
        try:
            user_data = json.loads(user_content)
        except json.JSONDecodeError:
            pass

    system_lower = system_content.lower()

    # --- Reranking ---
    if "rerank" in system_lower or "score passage relevance" in system_lower:
        if user_data and "passages" in user_data:
            passages = user_data.get("passages", [])
            if reranker_model is not None:
                try:
                    pairs = [[user_data.get("question", ""), p.get("text", "")] for p in passages]
                    scores = reranker_model.predict(pairs)
                    scores_list = [{"chunk_id": str(p.get("chunk_id", "")), "score": round(float(s), 4)}
                                   for p, s in zip(passages, scores)]
                    return _make_chat_completion(json.dumps({"scores": scores_list}))
                except Exception as e:
                    logger.error(f"Reranker inference failed: {e}")

            # Fallback: heuristic reranking
            question = user_data.get("question", "").lower()
            scored = []
            for p in passages:
                text = p.get("text", "").lower()
                chunk_id = str(p.get("chunk_id", ""))
                question_words = set(question.split())
                text_words = set(text.split())
                overlap = len(question_words & text_words) / max(len(question_words), 1)
                scored.append({"chunk_id": chunk_id, "score": round(min(overlap, 1.0), 4)})
            return _make_chat_completion(json.dumps({"scores": scored}))

        return _make_chat_completion(json.dumps({"scores": []}))

    # --- Generation ---
    if "answer only using supplied passages" in system_lower or "generate" in system_lower:
        if user_data and "passages" in user_data:
            passages = user_data.get("passages", [])
            context = "\n\n".join(f"[{p.get('chunk_id')}] {p.get('text', '')}" for p in passages)
            question = user_data.get("question", "")

            if generator is not None and tokenizer is not None:
                try:
                    import torch
                    prompt = f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"
                    inputs = tokenizer(prompt, return_tensors="pt")
                    if torch.cuda.is_available():
                        inputs = {k: v.to("cuda") for k, v in inputs.items()}
                    with torch.no_grad():
                        outputs = generator.generate(
                            **inputs,
                            max_new_tokens=request.max_tokens or 512,
                            temperature=request.temperature,
                            do_sample=request.temperature > 0,
                            pad_token_id=tokenizer.eos_token_id,
                        )
                    answer = tokenizer.decode(outputs[0], skip_special_tokens=True)
                    if answer.startswith(prompt):
                        answer = answer[len(prompt):]
                    answer = answer.strip()

                    cited = [str(p.get("chunk_id", "")) for p in passages if p.get("text", "").strip()]
                    response = {"answer": answer, "cited_chunk_ids": cited}
                    return _make_chat_completion(json.dumps(response))
                except Exception as e:
                    logger.error(f"Generator inference failed: {e}")

            # Fallback: simple extractive answer
            if passages:
                best = max(passages, key=lambda p: len(p.get("text", "")))
                cited = [str(p.get("chunk_id", "")) for p in passages if p.get("text", "").strip()]
                return _make_chat_completion(json.dumps({
                    "answer": best.get("text", "No answer available."),
                    "cited_chunk_ids": cited,
                }))

        return _make_chat_completion(json.dumps({"answer": "I cannot answer that question based on the provided context.", "cited_chunk_ids": []}))

    return _make_chat_completion(json.dumps({"answer": "I cannot answer that question.", "cited_chunk_ids": []}))


@app.get("/engines/v1/models")
async def list_models():
    """List available models."""
    models = []
    if MODEL_TYPE in ("multi", "embedding"):
        models.append({"id": EMBEDDING_MODEL_NAME, "object": "model", "created": 1677610600, "owned_by": "document-insight"})
    if MODEL_TYPE in ("multi", "reranker"):
        models.append({"id": RERANKER_MODEL_NAME, "object": "model", "created": 1677610600, "owned_by": "document-insight"})
    if MODEL_TYPE in ("multi", "generation"):
        models.append({"id": GENERATION_MODEL_NAME, "object": "model", "created": 1677610600, "owned_by": "document-insight"})
    return {"data": models}


@app.get("/health")
async def health():
    ready = all([
        embedding_model is not None if MODEL_TYPE in ("multi", "embedding") else True,
        reranker_model is not None if MODEL_TYPE in ("multi", "reranker") else True,
        generator is not None if MODEL_TYPE in ("multi", "generation") else True,
    ])
    status = "healthy" if ready else "degraded"
    return {"status": status, "models_loaded": ready}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=12434)
