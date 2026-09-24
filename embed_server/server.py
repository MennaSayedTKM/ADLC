"""
server.py
Standalone embedding server for Qwen3-VL-Embedding-2B-vdr — the same model,
prompts and pooling as colab_embed_server.ipynb, packaged to run as a
service on the AWS GPU instance (see infra/) instead of Colab + ngrok.

Keep the model, instruction prefixes and pooling identical to the notebook:
vectors from this server and from Colab must land in the same space, or
tiles already in the FAISS index stop matching new queries.

Endpoints (the contract ai/embed_client.py expects):
    GET  /health       -> {"status": "ok", "device": "cuda"}
    POST /embed_image  {"image_b64": str} -> {"embedding": [...], "dim": int}
    POST /embed_text   {"text": str}      -> {"embedding": [...], "dim": int}

Run:  uvicorn server:app --host 0.0.0.0 --port 8000
"""

import base64
import io
import os
import threading
from typing import List

import torch
import torch.nn.functional as F
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel
from transformers import AutoModel, AutoProcessor

MODEL_ID = os.environ.get("EMBED_MODEL_ID", "tomaarsen/Qwen3-VL-Embedding-2B-vdr")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Instruction prefixes — VDR models benefit from task-specific prompts.
IMAGE_INSTRUCTION = (
    "Represent this document image for retrieval, including all visible text, "
    "charts, figures, tables, and diagrams."
)
TEXT_INSTRUCTION = "Query: "

processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
model = AutoModel.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.float16,
    trust_remote_code=True,
    device_map="auto",
)
model.eval()

# One GPU, one model: serialize forward passes rather than let concurrent
# requests contend for VRAM.
_gpu_lock = threading.Lock()


def _mean_pool(hidden_states: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Weighted mean pooling — ignores padding tokens."""
    mask = attention_mask.unsqueeze(-1).float()
    summed = (hidden_states * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return F.normalize(summed / counts, p=2, dim=-1)


def _embed(messages: list, images: list | None = None) -> list:
    text_prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    kwargs = {"text": [text_prompt], "return_tensors": "pt", "padding": True}
    if images:
        kwargs["images"] = images
    inputs = processor(**kwargs).to(DEVICE)
    with _gpu_lock, torch.no_grad():
        outputs = model(**inputs, output_hidden_states=True)
        embedding = _mean_pool(outputs.hidden_states[-1], inputs["attention_mask"])
    return embedding[0].float().cpu().tolist()


def embed_image_pil(pil_image: Image.Image) -> list:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": pil_image},
                {"type": "text", "text": IMAGE_INSTRUCTION},
            ],
        }
    ]
    return _embed(messages, images=[pil_image])


def embed_text_query(text: str) -> list:
    messages = [{"role": "user", "content": [{"type": "text", "text": TEXT_INSTRUCTION + text}]}]
    return _embed(messages)


app = FastAPI(title="ADLC Embedding Server")


class ImageRequest(BaseModel):
    image_b64: str  # base64-encoded PNG/JPEG


class TextRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    embedding: List[float]
    dim: int


@app.get("/health")
def health():
    return {"status": "ok", "device": DEVICE, "model": MODEL_ID}


@app.post("/embed_image", response_model=EmbedResponse)
def embed_image_endpoint(req: ImageRequest):
    try:
        pil_image = Image.open(io.BytesIO(base64.b64decode(req.image_b64))).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot decode image: {e}")
    try:
        vec = embed_image_pil(pil_image)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")
    return EmbedResponse(embedding=vec, dim=len(vec))


@app.post("/embed_text", response_model=EmbedResponse)
def embed_text_endpoint(req: TextRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    try:
        vec = embed_text_query(req.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")
    return EmbedResponse(embedding=vec, dim=len(vec))
