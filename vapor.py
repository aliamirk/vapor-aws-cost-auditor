"""Vapor CLI - backward compatible entry point.

Allows running via: python vapor.py [OPTIONS]
For installed usage: vapor [OPTIONS]
"""

from vapor.cli import main

if __name__ == "__main__":
    main()
