import requests

from src.core.bot import MusicPartnerBot
from src.utils.config import Config
from src.utils.logger import Logger
from src.utils.notification import NotificationService
from src.validators.cookie import CookieValidator


def main():
    logger = Logger()
    notifier = None
    try:
        # 初始化基础组件
        config = Config()
        notifier = NotificationService(config, logger)
        config.validate_required(["Cookie_MUSIC_U", "Cookie___csrf"], "主程序")
        
        # 创建会话并设置Cookie
        session = requests.Session()
        session.cookies.set("MUSIC_U", config.get("Cookie_MUSIC_U"))
        session.cookies.set("__csrf", config.get("Cookie___csrf"))
        
        # 验证Cookie
        validator = CookieValidator(session, logger, timeout=config.get_http_timeout())
        is_valid, message = validator.validate()
        
        if not is_valid:
            logger.error(message)
            notifier.send_notification(
                "网易云音乐合伙人 - Cookie失效提醒", 
                f"请更新Cookie\n详细信息: {message}"
            )
            return
        
        # 运行主程序
        bot = MusicPartnerBot(config, logger, session)
        success = bot.run()
        
        # 处理执行结果
        end_message = "✅ 执行成功" if success else "❌ 执行失败"
        logger.end(end_message, not success)
        
        if not success:
            notifier.send_notification(
                "网易云音乐合伙人 - 执行失败提醒",
                "程序执行失败，请检查日志"
            )
            
    except Exception as e:
        error_message = f"程序异常: {str(e)}"
        logger.error(error_message)
        logger.end("❌ 执行失败", True)
        
        if notifier:
            try:
                notifier.send_notification(
                    "网易云音乐合伙人 - 异常提醒",
                    error_message
                )
            except Exception as notify_error:
                logger.error(f"发送异常通知时出错: {str(notify_error)}")

if __name__ == "__main__":
    main()
