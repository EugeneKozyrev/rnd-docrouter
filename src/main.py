import os
import base64
import asyncio
import pymupdf
import httpx
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from typing import List

app = FastAPI(
    title="docrouter",
    description="",
    version="0.1.0",
)

TIKA_URL = os.getenv("TIKA_URL", "")
VLM_API_URL = os.getenv("VLM_API_URL", "")
VLM_API_KEY = os.getenv("VLM_API_KEY", "")
VLM_DEFAULT_MODEL = os.getenv("VLM_DEFAULT_MODEL", "")

TEXT_THRESHOLD_PER_PAGE = int(os.getenv("TEXT_THRESHOLD_PER_PAGE", 50)) # минимум символов на страницу, чтобы считать PDF текстовым

VLM_CONCURRENCY = int(os.getenv("VLM_CONCURRENCY", 5)) # ограничение одновременных запросов к VLM

MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 50) * 1024 * 1024) # Максимальный размер файла

def _check_text_layer(pdf_bytes: bytes) -> bool:
    """Проверяет, содержит ли PDF значимый текстовый слой."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page_count = len(doc)
    total_text = sum(len(page.get_text().strip()) for page in doc)
    doc.close()
    return total_text > page_count * TEXT_THRESHOLD_PER_PAGE


def _pdf_to_images(pdf_bytes: bytes) -> List[bytes]:
    """Конвертирует PDF в PNG-изображения (масштаб 2x для лучшего качества)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
        images.append(pix.tobytes("png"))
    doc.close()
    return images


async def _extract_page_vlm(img_bytes: bytes) -> str:
    """Запрашивает текст у VLM для одной страницы."""
    b64 = base64.b64encode(img_bytes).decode()
    payload = {
        "model": VLM_DEFAULT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "Извлеки ВЕСЬ видимый текст с изображения. Сохрани структуру, переносы строк и таблицы. Верни ТОЛЬКО текст, без пояснений."
            },
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]
            }
        ],
        "max_tokens": 4000
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{VLM_API_URL.rstrip('/')}/chat/completions", json=payload, headers={"Authorization": f"Bearer {VLM_API_KEY}"})
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _extract_text_with_vlm(images: List[bytes]) -> str:
    """Параллельно обрабатывает страницы через VLM с ограничением конкурентности."""
    semaphore = asyncio.Semaphore(VLM_CONCURRENCY)

    async def limited_extract(img: bytes) -> str:
        async with semaphore:
            return await _extract_page_vlm(img)

    tasks = [limited_extract(img) for img in images]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    texts = []
    for r in results:
        if isinstance(r, Exception):
            texts.append(f"[❌ ОШИБКА VLM: {str(r)}]")
        else:
            texts.append(r)
    return "\n\n--- СТРАНИЦА ---\n\n".join(texts)


async def _proxy_to_tika(file_bytes: bytes, content_type: str) -> str:
    """Проксирует запрос в Apache Tika."""
    async with httpx.AsyncClient(timeout=120) as client:
        headers = {"Content-Type": content_type}
        resp = await client.put(TIKA_URL, content=file_bytes, headers=headers)
        resp.raise_for_status()
        return resp.text


@app.put("/v1/api/process")
async def process_document(file: UploadFile):
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Файл слишком большой")

    content_type = file.content_type or "application/octet-stream"
    is_pdf = content_type == "application/pdf" or file_bytes.startswith(b"%PDF")

    try:
        if is_pdf and not _check_text_layer(file_bytes):
            images = _pdf_to_images(file_bytes)
            if not images:
                raise HTTPException(status_code=400, detail="PDF не содержит страниц")
            text = await _extract_text_with_vlm(images)
            return JSONResponse({"text": text, "source": "vlm", "status": "success"})

        tika_text = await _proxy_to_tika(file_bytes, content_type)
        return JSONResponse({"text": tika_text, "source": "tika", "status": "success"})

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Ошибка внешнего сервиса: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка маршрутизации: {str(e)}")

@app.get("/health", summary="Health check", tags=["Monitoring"])
async def health_check():
    return JSONResponse(status_code=200, content={"status": "ok"})
