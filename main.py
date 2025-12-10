import logging

logger = logging.getLogger(__name__)


def main():
    logger.info("Hello from video-ai!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
