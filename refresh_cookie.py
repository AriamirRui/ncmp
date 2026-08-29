import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from src.core.pipeline import prepare_refresh_env, run_cookie_refresh
from src.utils.config import Config
from src.utils.logger import Logger
from src.utils.notification import NotificationService


def main():
    try:
        # 初始化基础组件
        config = Config()
        logger = Logger()
        notifier = NotificationService(config, logger)

        # 将配置中的登录/GitHub 信息注入环境变量
        prepare_refresh_env(config)

        # 初始化并执行刷新任务
        success = run_cookie_refresh(config, logger, notifier)
        
        # 处理执行结果
        if success:
            logger.info("✅ Cookie刷新成功")
        else:
            logger.error("❌ Cookie刷新失败")
            
    except Exception as e:
        error_message = f"Cookie刷新程序异常: {str(e)}"
        logger = Logger()
        logger.error(error_message)
        
        try:
            config = Config()
            notifier = NotificationService(config, logger)
            notifier.send_notification(
                "网易云音乐合伙人 - Cookie刷新异常",
                error_message
            )
        except Exception as notify_error:
            logger.error(f"发送异常通知时出错: {str(notify_error)}")


if __name__ == "__main__":
    main()
