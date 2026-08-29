import sys

from src.core.pipeline import run_pipeline
from src.utils.config import Config
from src.utils.logger import Logger
from src.utils.notification import NotificationService


def main():
    config = None
    logger = None
    notifier = None

    try:
        # 初始化基础组件
        config = Config()
        logger = Logger()
        notifier = NotificationService(config, logger)

        # 运行主流程（Cookie验证 + 每日任务 + 额外评分任务）
        result = run_pipeline(config, logger, notifier)

        # 处理执行结果
        end_message = "✅ 执行成功" if result.success else "❌ 执行失败"
        logger.end(end_message, not result.success)

        if not result.success:
            notifier.send_notification(
                "网易云音乐合伙人 - 执行失败提醒",
                f"{result.reason or '程序执行失败'}\n请检查日志"
            )

    except Exception as e:
        error_message = f"程序异常: {str(e)}"

        # 兜底初始化日志与通知（配置加载异常时也能打印）
        if logger is None:
            logger = Logger()
        logger.error(error_message)
        logger.end("❌ 执行失败", True)

        try:
            if notifier is None:
                config = Config() if config is None else config
                notifier = NotificationService(config, logger)
            notifier.send_notification(
                "网易云音乐合伙人 - 异常提醒",
                error_message
            )
        except Exception as notify_error:
            logger.error(f"发送异常通知时出错: {str(notify_error)}")


if __name__ == "__main__":
    if "--gui" in sys.argv:
        from gui import run_gui
        run_gui()
    else:
        main()
