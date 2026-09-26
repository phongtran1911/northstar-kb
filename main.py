from dotenv import load_dotenv

from src.sync import sync


def main() -> None:
    load_dotenv()
    count = sync()
    print(f"Synced {count} articles")


if __name__ == "__main__":
    main()
