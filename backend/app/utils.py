import re
from typing import List, Set

# Regex pattern for @mention:
# Matches `@` followed by alphanumeric characters and underscores.
# It makes sure that the `@` is at the beginning of the string or preceded by a non-word character (like spaces or punctuation),
# to avoid matching email addresses (e.g. user@domain.com).
MENTION_REGEX = re.compile(r"(?<=^|(?<=[^a-zA-Z0-9_\.]))@([a-zA-Z0-9_]+)")

def parse_mentions(text: str, author: str = None) -> List[str]:
    """
    Parses @mentions from a comment text.
    
    Guarantees:
    1. Case-insensitivity (all usernames returned as lowercase)
    2. De-duplication within the same comment
    3. Safe boundary checking (won't match emails or invalid symbols)
    4. Filters out self-mentions (e.g. if john mentions @john, no notification is sent)
    
    :param text: The raw text comment to parse
    :param author: The author of the comment (optional, used to prevent self-mentions)
    :return: A list of unique, lowercased usernames mentioned in the text
    """
    if not text:
        return []

    # Find all matches using the compiled regex
    matches = MENTION_REGEX.findall(text)
    
    # Process matches: lowercase to ensure case-insensitivity
    mentioned_users: Set[str] = {match.lower() for match in matches}
    
    # Filter out self-mentions
    if author:
        author_lower = author.lower()
        mentioned_users = {user for user in mentioned_users if user != author_lower}
        
    return list(mentioned_users)
