"""
Difficulty Level Definitions for Government Programs
=====================================================
This is the SOURCE OF TRUTH for difficulty classifications.
The frontend has a matching file: /lib/difficultyLevels.ts

Keep both files in sync when making changes!
"""

DIFFICULTY_LEVELS = {
    "easy": {
        "key": "easy",
        "label": "Easy",
        "emoji": "🟢",
        "color": "green",
        "documents": "1-3 documents",
        "process": "Online application",
        "timeline": "Days to 1 week",
        "description": "Simple online process with minimal paperwork"
    },
    "medium": {
        "key": "medium", 
        "label": "Medium",
        "emoji": "🟡",
        "color": "yellow",
        "documents": "4-6 documents",
        "process": "Mixed online & in-person",
        "timeline": "1-2 weeks",
        "description": "Some paperwork and possible office visit"
    },
    "complex": {
        "key": "complex",
        "label": "Complex",
        "emoji": "🔴",
        "color": "red",
        "documents": "7+ documents",
        "process": "In-person required",
        "timeline": "Weeks to months",
        "description": "Multiple requirements and office visits needed"
    }
}

# Valid difficulty keys for validation
VALID_DIFFICULTIES = list(DIFFICULTY_LEVELS.keys())

def get_difficulty_info(difficulty_key: str) -> dict:
    """Get difficulty information by key. Returns 'medium' as default."""
    return DIFFICULTY_LEVELS.get(difficulty_key, DIFFICULTY_LEVELS["medium"])
