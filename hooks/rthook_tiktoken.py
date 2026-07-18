import os, sys

# Point tiktoken to the bundled BPE files instead of downloading from the internet
_base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('TIKTOKEN_CACHE_DIR', os.path.join(_base, 'tiktoken_cache'))
