"""DLP (Data Loss Prevention) Scanner."""

import re

class DLPScanner:
    """Regex-based DLP scanning to flag sensitive outgoing information."""
    
    PATTERNS = {
        "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
        "api_key": re.compile(r"sk-[a-zA-Z0-9]{32,}") # e.g. OpenAI keys
    }

    def scan(self, content: str) -> bool:
        """Return True if any sensitive data pattern is matched."""
        if not content:
            return False
            
        for name, pattern in self.PATTERNS.items():
            if pattern.search(content):
                return True
        return False

dlp_scanner = DLPScanner()
