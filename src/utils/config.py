import json
import os
import random
from typing import Any, Dict, Iterable


class Config:
    def __init__(self):
        self.config_data: Dict = self._load_config()
    
    def _load_config(self) -> Dict:
        config = self._load_from_file()
        config.update(self._load_from_env())
        self._apply_defaults(config)
        return config
    
    def _load_from_env(self) -> Dict:
        config = {}
        
        # Cookie 环境变量只在显式提供时覆盖文件配置
        if music_u := os.getenv("MUSIC_U"):
            config["Cookie_MUSIC_U"] = music_u
        if csrf := os.getenv("CSRF"):
            config["Cookie___csrf"] = csrf
        
        # 可选的环境变量
        if notify_email := os.getenv("NOTIFY_EMAIL"):
            config["notify_email"] = notify_email
        if email_password := os.getenv("EMAIL_PASSWORD"):
            config["email_password"] = email_password
        if smtp_server := os.getenv("SMTP_SERVER"):
            config["smtp_server"] = smtp_server
        if smtp_port := os.getenv("SMTP_PORT"):
            config["smtp_port"] = int(smtp_port)
        if wait_min := os.getenv("WAIT_TIME_MIN"):
            config["wait_time_min"] = float(wait_min)
        if wait_max := os.getenv("WAIT_TIME_MAX"):
            config["wait_time_max"] = float(wait_max)
        if score := os.getenv("SCORE"):
            config["score"] = int(score)
        if full_extra_tasks := os.getenv("FULL_EXTRA_TASKS"):
            config["full_extra_tasks"] = full_extra_tasks.lower() in ("1", "true", "yes")
            
        # 自动登录相关配置
        if phone := os.getenv("NETEASE_PHONE"):
            config["netease_phone"] = phone
        if password := os.getenv("NETEASE_PASSWORD"):
            config["netease_password"] = password
        if md5_password := os.getenv("NETEASE_MD5_PASSWORD"):
            config["netease_md5_password"] = md5_password
            
        # GitHub相关配置
        if gh_token := os.getenv("GH_TOKEN"):
            config["gh_token"] = gh_token
        if gh_repo := os.getenv("GH_REPO"):
            config["gh_repo"] = gh_repo
        
        return config
    
    def _load_from_file(self) -> Dict:
        try:
            config_path = "config/setting.json"
            if not os.path.exists(config_path):
                return {}
                
            with open(config_path, "r", encoding="utf-8") as file:
                config = json.loads(file.read())

            return config
            
        except Exception as e:
            raise RuntimeError(f"配置加载失败: {str(e)}")

    def _apply_defaults(self, config: Dict) -> None:
        config.setdefault("wait_time_min", 15)
        config.setdefault("wait_time_max", 20)
        config.setdefault("smtp_server", "smtp.gmail.com")
        config.setdefault("smtp_port", 465)
        config.setdefault("score", 0)
        config.setdefault("full_extra_tasks", False)
        config.setdefault("http_timeout", 15)
        config.setdefault("rate_limit_retries", 3)

    def validate_required(self, required_keys: Iterable[str], context: str) -> None:
        missing_keys = [key for key in required_keys if not self.get(key)]
        if missing_keys:
            missing = ", ".join(missing_keys)
            raise ValueError(f"{context}缺少必要配置项: {missing}")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        return self.config_data.get(key, default)

    def get_wait_time(self) -> float:
        """获取随机等待时间"""
        min_time = float(self.get("wait_time_min", 15))
        max_time = float(self.get("wait_time_max", 20))
        return random.uniform(min_time, max_time)

    def get_http_timeout(self) -> float:
        """获取 HTTP 请求超时时间"""
        return float(self.get("http_timeout", 15))
