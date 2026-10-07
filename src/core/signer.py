import base64
import codecs
import json
import random
import string
import time
from typing import Tuple

import requests
from Crypto.Cipher import AES

from ..utils.config import Config
from ..utils.http import request_json
from ..utils.logger import Logger
from .reviews import evaluate_comments


class Signer:
    def __init__(self, session: requests.Session, task_id: str, logger: Logger, config: Config):
        self.session = session
        self.task_id = task_id
        self.logger = logger
        self.config = config
        self.sign_url = "https://interface.music.163.com/weapi/music/partner/work/evaluate"
        
        # 加密相关常量
        self.random_str = self._generate_random_string(16)
        self.pub_key = "010001"
        self.modulus = "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"
        self.iv = "0102030405060708"
        self.aes_key = "0CoJUm6Qyw8W8jud"
        
    def _generate_random_string(self, length: int) -> str:
        """生成指定长度的随机字符串"""
        return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(length))

    def _add_to_16(self, text: str) -> bytes:
        """将字符串补充到16的倍数"""
        pad = 16 - len(text) % 16
        text = text + chr(pad) * pad
        return text.encode('utf-8')

    def _aes_encrypt(self, text: str, key: str) -> str:
        """AES加密"""
        encryptor = AES.new(key.encode('utf-8'), AES.MODE_CBC, self.iv.encode('utf-8'))
        encrypt_text = encryptor.encrypt(self._add_to_16(text))
        return base64.b64encode(encrypt_text).decode('utf-8')

    def _get_params(self, data: dict) -> str:
        """获取加密后的参数"""
        text = json.dumps(data)
        params = self._aes_encrypt(text, self.aes_key)
        params = self._aes_encrypt(params, self.random_str)
        return params

    def _get_enc_sec_key(self) -> str:
        """获取加密密钥"""
        text = self.random_str[::-1]
        rs = int(codecs.encode(text.encode('utf-8'), 'hex_codec'), 16)
        rs = pow(rs, int(self.pub_key, 16), int(self.modulus, 16))
        return format(rs, 'x').zfill(256)

    def _get_evaluation(self, work: dict) -> Tuple[str, str, str]:
        """获取待提交的分数、标签和评价；评论不可用时记录原因并回退。"""
        strategy = self.config.get("score", 0)
        if isinstance(strategy, bool) or not isinstance(strategy, int) or strategy not in range(5):
            raise ValueError("score 必须是 0～4 的整数")
        if strategy == 0:
            try:
                evaluation = self._get_comment_evaluation(work)
                if evaluation is not None:
                    self.logger.info(f'歌曲「{work["name"]}」参考评价：{evaluation[2]}')
                    return evaluation
                reason = "可用的独立音乐评价不足 3 条"
            except (RuntimeError, ValueError, TypeError) as exc:
                reason = str(exc)
            self.logger.warning(f'歌曲「{work["name"]}」无法参考评论：{reason}；回退为 3 分，不填写评价')
            return "3", "3-A-1", ""

        # 保留原有分数范围，去掉歌名和作者名中英文字符带来的偏差。
        score = str(random.randint(strategy, strategy + 1)) if strategy < 4 else "4"
        return score, f"{score}-A-1", ""

    def _get_comment_evaluation(self, work: dict) -> Tuple[str, str, str] | None:
        """通过歌曲 resourceId 读取一页公开评论，不使用合伙人的 workId 查询歌曲。"""
        resource_id = str(work.get("resourceId", ""))
        if not resource_id.isascii() or not resource_id.isdigit() or int(resource_id) <= 0:
            raise ValueError("缺少有效的歌曲 resourceId")
        if work.get("resourceType", "SONG") != "SONG":
            raise ValueError("资源不是歌曲，无法读取歌曲评论")
        data = {
            "rid": resource_id,
            "limit": 20,
            "offset": 0,
            "beforeTime": 0,
            "csrf_token": str(self.session.cookies["__csrf"]),
        }
        payload = request_json(
            self.session,
            "POST",
            f"https://music.163.com/weapi/v1/resource/comments/R_SO_4_{resource_id}",
            self.logger,
            timeout=self.config.get_http_timeout(),
            error_context="获取歌曲公开评论",
            data={"params": self._get_params(data), "encSecKey": self._get_enc_sec_key()},
            headers={"Referer": "https://music.163.com/"},
        )
        if not isinstance(payload, dict) or payload.get("code") != 200:
            raise RuntimeError("公开评论接口未返回成功结果")
        hot_comments = payload.get("hotComments", [])
        comments = payload.get("comments", [])
        if not isinstance(hot_comments, list) or not isinstance(comments, list):
            raise RuntimeError("公开评论接口返回的评论列表格式异常")
        return evaluate_comments(hot_comments + comments)

    def sign(self, work: dict, is_extra: bool = False) -> None:
        """为作品评分"""
        try:
            csrf = str(self.session.cookies["__csrf"])
            max_retries = max(int(self.config.get("rate_limit_retries", 3)), 0)

            # 同一作品只生成一次评价，限流重试时复用，避免改分或重复查询评论。
            score, tag, comment = self._get_evaluation(work)
            data = {
                "taskId": self.task_id,
                "workId": work['id'],
                "score": score,
                "tags": tag,
                "customTags": "%5B%5D",
                "comment": comment,
                "syncYunCircle": False if comment else "true",
                "csrf_token": csrf
            }
            if comment:
                data["syncComment"] = False
            if is_extra:
                data["extraResource"] = "true"

            for attempt in range(max_retries + 1):
                delay = self.config.get_wait_time()
                self.logger.info(f"等待 {delay:.1f} 秒后继续...")
                time.sleep(delay)

                params = {
                    "params": self._get_params(data),
                    "encSecKey": self._get_enc_sec_key()
                }

                self.logger.debug(f"评分请求数据: {data}")
                response = self.session.post(
                    url=f'{self.sign_url}?csrf_token={csrf}',
                    data=params,
                    timeout=self.config.get_http_timeout(),
                )
                response.raise_for_status()
                payload = response.json()
                self.logger.debug(f"评分响应数据: {payload}")

                if payload["code"] == 200:
                    self.logger.info(f'{work["name"]}「{work["authorName"]}」评分完成：{score}分')
                    return

                error_msg = payload.get('message') or payload.get('msg', '未知错误')
                if "频繁" in error_msg:
                    if attempt >= max_retries:
                        raise RuntimeError(
                            f"评分失败: 已达到频率限制最大重试次数 {max_retries}"
                        )
                    retry_delay = self.config.get_wait_time()
                    self.logger.info(
                        f"遇到频率限制，等待 {retry_delay:.1f} 秒后进行第 {attempt + 1}/{max_retries} 次重试..."
                    )
                    time.sleep(retry_delay)
                    continue
                if payload["code"] == 405 and "资源状态异常" in error_msg:
                    self.logger.warning(f'歌曲「{work["name"]}」资源状态异常，跳过')
                    return
                raise RuntimeError(f"评分失败: {error_msg} (响应码: {payload.get('code')})")
                
        except Exception as e:
            self.logger.error(f'歌曲「{work["name"]}」评分异常：{str(e)}')
            raise RuntimeError(f"评分过程出错: {str(e)}")
