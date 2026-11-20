import base64
import io
import os

import requests

from .document_ingest import extract_text_from_learning_asset


_LOCAL_ENGINE = None
_LOCAL_ENGINE_ERROR = ""
_LOCAL_ENGINE_READY = None

# 本地 OCR 默认最大边，避免超大截图推理过慢
_LOCAL_OCR_MAX_SIDE = 2200


def _get_ocr_config():
    return {
        "provider": (os.getenv("OCR_PROVIDER", "auto") or "auto").strip().lower(),
        "api_key": os.getenv("QWEN_API_KEY", ""),
        "api_url": os.getenv(
            "QWEN_API_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        ),
        "model_name": os.getenv("QWEN_VL_MODEL_NAME", "qwen-vl-plus"),
        "local_fallback_enabled": str(os.getenv("OCR_LOCAL_FALLBACK_ENABLED", "true")).strip().lower() == "true",
    }


def local_ocr_available():
    """本地离线 OCR（RapidOCR / onnxruntime）是否可用。"""
    return _get_local_engine() is not None


def _get_local_engine():
    global _LOCAL_ENGINE, _LOCAL_ENGINE_ERROR, _LOCAL_ENGINE_READY
    if _LOCAL_ENGINE_READY is not None:
        return _LOCAL_ENGINE

    try:
        from rapidocr_onnxruntime import RapidOCR

        _LOCAL_ENGINE = RapidOCR()
        _LOCAL_ENGINE_READY = True
    except Exception as exc:  # 依赖缺失或模型加载失败
        _LOCAL_ENGINE = None
        _LOCAL_ENGINE_READY = False
        _LOCAL_ENGINE_ERROR = str(exc) or exc.__class__.__name__
    return _LOCAL_ENGINE


def _decode_image_for_ocr(raw_bytes):
    """把图片字节解码为可用于 OCR 的 RGB 数组（超图会等比缩小）。"""
    import numpy as np
    from PIL import Image

    image = Image.open(io.BytesIO(raw_bytes))
    image.load()
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    width, height = image.size
    max_side = max(width, height)
    if max_side > _LOCAL_OCR_MAX_SIDE:
        ratio = _LOCAL_OCR_MAX_SIDE / float(max_side)
        image = image.resize((max(1, int(width * ratio)), max(1, int(height * ratio))))
    return np.array(image)


def run_local_ocr(raw_bytes):
    """执行本地 OCR，返回 (text, error_message)。"""
    if not raw_bytes:
        return "", "图片内容为空"
    engine = _get_local_engine()
    if engine is None:
        return "", _LOCAL_ENGINE_ERROR or "本地 OCR 不可用"
    try:
        image_array = _decode_image_for_ocr(raw_bytes)
        result, _ = engine(image_array)
    except Exception as exc:
        return "", str(exc) or exc.__class__.__name__

    if not result:
        return "", ""

    lines = []
    for line in result:
        try:
            text = str(line[1] or "").strip()
        except Exception:
            continue
        if text:
            lines.append(text)

    # 把同一段被换行切开的多行合并成完整句子：只有上一行以句末标点结束才换行
    merged = []
    for line in lines:
        if not merged:
            merged.append(line)
            continue
        previous = merged[-1]
        if previous and previous[-1] in "。！？.!?:;；：)]】":
            merged.append(line)
        else:
            separator = "" if previous.endswith(("-", "/")) else " "
            merged[-1] = previous + separator + line
    return "\n".join(merged).strip(), ""


def _build_local_ocr_fallback(file_storage, provider: str, reason_code: str, reason_message: str):
    file_storage.stream.seek(0)
    raw = file_storage.read()
    file_storage.stream.seek(0)

    name = str(getattr(file_storage, "filename", "") or "学习图片").strip() or "学习图片"

    local_text, local_error = run_local_ocr(raw)
    if local_text:
        return {
            "success": True,
            "text": local_text,
            "ai_used": False,
            "provider": "rapidocr_local",
            "error_code": "",
            "error_message": "",
            "fallback_used": True,
            "synthetic": False,
            "upstream_error_code": reason_code,
            "upstream_error_message": reason_message,
        }

    extracted = extract_text_from_learning_asset(
        name=name,
        mime=str(getattr(file_storage, "mimetype", "") or ""),
        content="",
        summary="",
        file_bytes=raw,
    )
    text = str(extracted.get("text") or "").strip()
    synthetic = not bool(text)
    if synthetic:
        # 占位文本只用于前端提示，不代表真实识别结果，调用方不应写入知识库或当作题干。
        stem = os.path.splitext(name)[0].replace("_", " ").replace("-", " ").strip()
        if stem:
            text = f"离线OCR兜底：已接收图片《{name}》。可识别关键词：{stem}。"
        else:
            text = f"离线OCR兜底：已接收图片《{name}》，请在提问框补充题干文本。"

    return {
        "success": not synthetic,
        "text": text,
        "ai_used": False,
        "provider": "rapidocr_local" if local_error else f"{provider}_local_fallback",
        "error_code": reason_code or ("OCR_LOCAL_NO_TEXT" if local_error else ""),
        "error_message": reason_message or (f"本地OCR未识别到文字：{local_error}" if local_error else ""),
        "fallback_used": True,
        "synthetic": synthetic,
    }


def extract_text_from_image(file_storage):
    """OCR：从图片中提取文本。

    OCR_PROVIDER 支持：
    - auto（默认）：有 QWEN_API_KEY 时走 qwen_vl，否则用本地离线 OCR（RapidOCR）
    - local / rapidocr：只用本地离线 OCR
    - qwen_vl：云端视觉模型，失败或未配置 key 时回退本地 OCR
    - mock：仅返回占位文案（测试用），不写入知识库
    """
    cfg = _get_ocr_config()
    provider = cfg["provider"]

    if not file_storage:
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": provider,
            "error_code": "OCR_EMPTY_FILE",
            "error_message": "未提供图片文件",
        }

    if provider in {"local", "rapidocr", "rapidocr_local", "onnx"}:
        return _build_local_ocr_fallback(
            file_storage,
            provider=provider,
            reason_code="",
            reason_message="",
        )

    if provider == "mock":
        return _build_local_ocr_fallback(
            file_storage,
            provider=provider,
            reason_code="OCR_PROVIDER_MOCK",
            reason_message="OCR_PROVIDER=mock，仅返回占位文本",
        )

    if provider == "auto" and not cfg["api_key"]:
        return _build_local_ocr_fallback(
            file_storage,
            provider=provider,
            reason_code="OCR_KEY_MISSING",
            reason_message="未配置 QWEN_API_KEY，使用本地离线 OCR",
        )

    if provider not in {"qwen_vl", "auto"}:
        if cfg["local_fallback_enabled"]:
            return _build_local_ocr_fallback(
                file_storage,
                provider=provider,
                reason_code="OCR_PROVIDER_DISABLED",
                reason_message=f"未知的 OCR_PROVIDER={provider}，已回退到本地离线 OCR",
            )
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": provider,
            "error_code": "OCR_PROVIDER_DISABLED",
            "error_message": f"未知的 OCR_PROVIDER={provider}",
        }

    if not cfg["api_key"]:
        if cfg["local_fallback_enabled"]:
            return _build_local_ocr_fallback(
                file_storage,
                provider="qwen_vl",
                reason_code="OCR_KEY_MISSING",
                reason_message="未配置 QWEN_API_KEY，已回退到本地离线 OCR",
            )
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": "qwen_vl",
            "error_code": "OCR_KEY_MISSING",
            "error_message": "未配置 QWEN_API_KEY",
        }

    file_storage.stream.seek(0)
    raw = file_storage.read()
    file_storage.stream.seek(0)

    try:
        ext = os.path.splitext(file_storage.filename or "")[1].lower()
        mime = "image/png" if ext == ".png" else "image/jpeg"
        b64 = base64.b64encode(raw).decode("utf-8")
        data_url = f"data:{mime};base64,{b64}"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        }
        payload = {
            "model": cfg["model_name"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请提取图片中的学习相关文字，只返回纯文本。"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "temperature": 0.2,
            "max_tokens": 800,
        }
        resp = requests.post(cfg["api_url"], headers=headers, json=payload, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        text = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
        if not text:
            return {
                "success": False,
                "text": "",
                "ai_used": False,
            "provider": "qwen_vl",
            "error_code": "OCR_EMPTY_RESPONSE",
            "error_message": "OCR返回内容为空",
        }

        return {
            "success": True,
            "text": text,
            "ai_used": True,
            "provider": "qwen_vl",
            "error_code": "",
            "error_message": "",
        }
    except Exception as e:
        if cfg["local_fallback_enabled"]:
            return _build_local_ocr_fallback(
                file_storage,
                provider="qwen_vl",
                reason_code="OCR_UPSTREAM_ERROR",
                reason_message=str(e),
            )
        return {
            "success": False,
            "text": "",
            "ai_used": False,
            "provider": "qwen_vl",
            "error_code": "OCR_UPSTREAM_ERROR",
            "error_message": str(e),
        }
