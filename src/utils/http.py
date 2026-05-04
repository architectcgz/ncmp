import json
from typing import Any, Dict, Optional

import requests

from .logger import Logger


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    logger: Logger,
    *,
    timeout: float,
    error_context: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """发送 HTTP 请求并返回 JSON，统一处理超时、状态码和解析错误。"""
    try:
        response = session.request(method=method, url=url, timeout=timeout, **kwargs)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"{error_context}失败: {exc}") from exc

    try:
        return response.json()
    except json.JSONDecodeError as exc:
        logger.debug(f"{error_context}原始响应: {response.text[:200]}")
        raise RuntimeError(f"{error_context}失败: 响应不是合法 JSON") from exc
