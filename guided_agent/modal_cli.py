"""`modal` CLI with IPv4 forced (see ipv4_only.py). Usage: python modal_cli.py deploy app.py"""
import sys
import ipv4_only  # noqa: F401
from modal.__main__ import main

sys.argv[0] = "modal"
main()
