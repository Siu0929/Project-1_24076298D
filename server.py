"""Convenience entry point for launching the web server from the project root."""

from src.web_server import main


if __name__ == "__main__":
    # Delegate startup to the main implementation module.
    main()
